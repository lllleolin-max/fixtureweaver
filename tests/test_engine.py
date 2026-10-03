import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

from fixtureweaver import FixtureError, weave


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.output = self.root / "source.db", self.root / "fixture.db"

    def tearDown(self):
        self.temp.cleanup()

    def database(self, sql):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.executescript(sql)

    def test_reduced_join_and_preserved_source(self):
        self.database("CREATE TABLE customer(id INTEGER PRIMARY KEY); CREATE TABLE orders(id INTEGER PRIMARY KEY, customer INTEGER REFERENCES customer(id)); INSERT INTO customer VALUES(1),(2); INSERT INTO orders VALUES(10,1),(11,2);")
        before = self.source.read_bytes()
        report = weave(self.source, self.output, {"seeds": [{"table": "orders", "where": "id=10"}], "masks": [{"name": "customer", "columns": [["customer", "id"]]}], "queries": [{"name": "join", "sql": "SELECT count(*) FROM orders JOIN customer ON customer.id=orders.customer", "expect": [[1]]}]})
        self.assertEqual(report["retained_rows"], {"customer": 1, "orders": 1})
        self.assertEqual(report["closure_added_rows"], 1)
        self.assertEqual(self.source.read_bytes(), before)
        with closing(sqlite3.connect(self.output)) as db, db:
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())

    def test_actual_affinity_nocase_composite_and_null(self):
        self.database("CREATE TABLE p(a INTEGER,b TEXT COLLATE NOCASE,PRIMARY KEY(a,b)) WITHOUT ROWID; CREATE TABLE c(id INTEGER PRIMARY KEY,x TEXT,y TEXT,FOREIGN KEY(x,y) REFERENCES p(a,b)); INSERT INTO p VALUES(1,'A'),(2,'B'); INSERT INTO c VALUES(1,'01','a'),(2,'bad',NULL);")
        report = weave(self.source, self.output, {"seeds": [{"table": "C"}], "masks": [{"name": "number", "columns": [["p", "a"]]}, {"name": "letter", "columns": [["p", "b"]]}], "queries": [{"name": "rows", "sql": "SELECT count(*) FROM c", "expect": [[2]]}]})
        self.assertEqual(report["retained_rows"]["p"], 1)
        with closing(sqlite3.connect(self.output)) as db, db:
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
            self.assertEqual(db.execute("SELECT y IS NULL FROM c WHERE id=2").fetchone(), (1,))

    def test_cyclic_closure(self):
        self.database("PRAGMA foreign_keys=ON; CREATE TABLE n(id INTEGER PRIMARY KEY,parent INTEGER REFERENCES n(id) DEFERRABLE INITIALLY DEFERRED); BEGIN; INSERT INTO n VALUES(1,2),(2,1),(3,3); COMMIT;")
        report = weave(self.source, self.output, {"seeds": [{"table": "n", "where": "id=1"}], "masks": [{"name": "n", "columns": [["n", "id"]]}]})
        self.assertEqual(report["retained_rows"], {"n": 2})
        self.assertEqual(report["dependency_edges"], 2)

    def test_bounds_and_existing_destination(self):
        self.database("CREATE TABLE n(id INTEGER PRIMARY KEY,parent INTEGER REFERENCES n(id)); INSERT INTO n VALUES(1,NULL),(2,1),(3,2);")
        with self.assertRaises(FixtureError) as error:
            weave(self.source, self.output, {"seeds": [{"table": "n", "where": "id=3"}], "limits": {"rows": 2}})
        self.assertEqual(error.exception.code, "CLOSURE_LIMIT")
        self.assertFalse(self.output.exists())
        self.output.write_text("keep")
        with self.assertRaises(FixtureError):
            weave(self.source, self.output, {"seeds": [{"table": "n"}]})
        self.assertEqual(self.output.read_text(), "keep")

    def test_consumer_query_failure_not_published(self):
        self.database("CREATE TABLE t(id INTEGER PRIMARY KEY); INSERT INTO t VALUES(1),(2);")
        with self.assertRaises(FixtureError) as error:
            weave(self.source, self.output, {"seeds": [{"table": "t", "where": "id=1"}], "queries": [{"name": "need_two", "sql": "SELECT count(*) FROM t", "expect": [[2]]}]})
        self.assertEqual(error.exception.code, "CONSUMER_QUERY")
        self.assertFalse(self.output.exists())

    def test_unsupported_trigger_and_dangling(self):
        self.database("CREATE TABLE p(id INTEGER PRIMARY KEY); CREATE TABLE c(id INTEGER REFERENCES p(id)); INSERT INTO c VALUES(8);")
        with self.assertRaises(FixtureError) as error:
            weave(self.source, self.output, {"seeds": [{"table": "c"}]})
        self.assertEqual(error.exception.code, "DANGLING")
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("DELETE FROM c")
            db.executescript("INSERT INTO p VALUES(1); CREATE TRIGGER trap AFTER INSERT ON p BEGIN SELECT 1; END;")
        with self.assertRaises(FixtureError) as error:
            weave(self.source, self.output, {"seeds": [{"table": "p"}]})
        self.assertEqual(error.exception.code, "UNSUPPORTED")

    def test_quoted_case_sensitive_unicode_names(self):
        self.database('CREATE TABLE "select"("ß" TEXT PRIMARY KEY,"ss" TEXT UNIQUE); INSERT INTO "select" VALUES(\'a\',\'b\');')
        report = weave(self.source, self.output, {"seeds": [{"table": "SELECT"}], "masks": [{"name": "id", "columns": [["select", "ß"]]}]})
        self.assertEqual(report["retained_rows"], {"select": 1})

    def test_implicit_rowid_and_desc_primary_key(self):
        self.database("CREATE TABLE item(id INTEGER PRIMARY KEY DESC, value TEXT); INSERT INTO item(rowid,id,value) VALUES(42,9,'retained'),(73,10,'dropped');")
        report = weave(self.source, self.output, {"seeds": [{"table": "item", "where": "id=9"}], "queries": [{"name": "rowid", "sql": "SELECT rowid,id FROM item", "expect": [[42,9]]}]})
        self.assertEqual(report["retained_rows"], {"item": 1})

    def test_protection_keeps_affinity_representations(self):
        self.database("CREATE TABLE p(id REAL PRIMARY KEY); CREATE TABLE c(id INTEGER PRIMARY KEY,p TEXT REFERENCES p(id)); INSERT INTO p VALUES(1.5); INSERT INTO c VALUES(7,'1.50');")
        report = weave(self.source, self.output, {"seeds": [{"table": "c"}], "masks": [{"name": "id", "columns": [["p", "id"]]}], "protect": [{"table": "c", "column": "p"}], "queries": [{"name": "representations", "sql": "SELECT p.id,c.p FROM c JOIN p ON p.id=c.p", "expect": [[1.5,"1.50"]]}]})
        self.assertEqual(report["masked_classes"][0]["pinned_equivalence_classes"], 1)


if __name__ == "__main__":
    unittest.main()
