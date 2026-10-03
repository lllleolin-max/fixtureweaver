from contextlib import closing
import copy
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sysconfig
import tempfile
import unittest

from fixtureweaver import FixtureError, weave


class AdversarialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.dest = self.root / "source.db", self.root / "out.db"

    def tearDown(self):
        self.temp.cleanup()

    def database(self, sql):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.executescript(sql)

    def refusal(self, plan, code):
        before = self.source.read_bytes()
        with self.assertRaises(FixtureError) as caught:
            weave(self.source, self.dest, plan)
        self.assertEqual(caught.exception.code, code)
        self.assertFalse(self.dest.exists())
        self.assertEqual(before, self.source.read_bytes())

    def test_unique_collision_from_incompatible_class_domains(self):
        # In a BINARY unique column A/a are distinct; the declared class also
        # uses a NOCASE domain that equates them. A uniform mask cannot retain
        # the original BINARY uniqueness. SQLite, not a Python set, rejects it.
        self.database("CREATE TABLE p(a TEXT UNIQUE); CREATE TABLE q(b TEXT COLLATE NOCASE); INSERT INTO p VALUES('A'),('a'); INSERT INTO q VALUES('A');")
        self.refusal({"seeds": [{"table": "p"},{"table": "q"}], "masks": [{"name": "id", "columns": [["p","a"],["q","b"]]}]}, "MASK_CONSTRAINT")

    def test_schema_conflict_policy_cannot_drop_retained_rows(self):
        for policy in ("REPLACE", "IGNORE", "FAIL"):
            with self.subTest(policy=policy):
                self.source.unlink(missing_ok=True)
                self.database(f"CREATE TABLE p(a TEXT UNIQUE ON CONFLICT {policy}); CREATE TABLE q(b TEXT COLLATE NOCASE); INSERT INTO p VALUES('A'),('a'); INSERT INTO q VALUES('A');")
                self.refusal({"seeds": [{"table": "p"},{"table": "q"}], "masks": [{"name": "id", "columns": [["p","a"],["q","b"]]}]}, "MASK_CONSTRAINT")

    def test_protected_value_colliding_with_generated_mask(self):
        self.database("CREATE TABLE p(id TEXT UNIQUE); INSERT INTO p VALUES('alpha');")
        plan = {"seeds": [{"table": "p"}], "masks": [{"name": "id", "columns": [["p","id"]]}]}
        first = self.root / "first.db"
        weave(self.source, first, plan)
        with closing(sqlite3.connect(first)) as db:
            token = db.execute("SELECT id FROM p").fetchone()[0]
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("INSERT INTO p VALUES(?)", (token,))
        plan["protect"] = [{"table": "p", "column": "id", "where": "id=?", "params": [token]}]
        self.refusal(plan, "MASK_CONSTRAINT")

    def test_overlapping_fk_classes_and_duplicates(self):
        self.database("CREATE TABLE p(id INTEGER PRIMARY KEY); CREATE TABLE c(id INTEGER REFERENCES p(id)); INSERT INTO p VALUES(1); INSERT INTO c VALUES(1);")
        self.refusal({"seeds": [{"table": "c"}], "masks": [{"name": "one", "columns": [["p","id"]]}, {"name": "two", "columns": [["c","id"]]}]}, "MASK_CONFLICT")
        report = weave(self.source, self.dest, {"seeds": [{"table": "c"},{"table": "c"}]})
        self.assertEqual(report["seed_rows"], 1)
        self.assertEqual(sum(report["retained_rows"].values()), 2)

    def test_check_partial_expression_unique_and_views(self):
        self.database("CREATE TABLE t(id INTEGER PRIMARY KEY,tag TEXT NOT NULL CHECK(length(tag)>0),active INTEGER); CREATE UNIQUE INDEX u ON t(lower(tag)) WHERE active=1; CREATE VIEW v AS SELECT tag FROM t WHERE active=1; INSERT INTO t VALUES(1,'a',1),(2,'b',0);")
        result = weave(self.source, self.dest, {"seeds": [{"table": "t"}], "masks": [{"name": "tag", "columns": [["t","tag"]]}], "queries": [{"name": "view", "sql": "SELECT count(*) FROM v", "expect": [[1]]}]})
        self.assertTrue(result["checks"]["integrity"])

    def test_check_refusal(self):
        self.database("CREATE TABLE t(id INTEGER PRIMARY KEY CHECK(id<100)); INSERT INTO t VALUES(1);")
        self.refusal({"seeds": [{"table": "t"}], "masks": [{"name": "id", "columns": [["t","id"]]}]}, "MASK_CONSTRAINT")

    def test_invalid_parent_unique_collation(self):
        self.database("CREATE TABLE p(id TEXT); CREATE UNIQUE INDEX u ON p(id COLLATE NOCASE); CREATE TABLE c(p TEXT REFERENCES p(id)); INSERT INTO p VALUES('A');")
        self.refusal({"seeds": [{"table": "p"}]}, "KEY_MODEL")

    def test_work_cell_result_and_value_bounds(self):
        self.database("CREATE TABLE t(a TEXT,b TEXT); INSERT INTO t VALUES('a','x'),('b','y');")
        self.refusal({"seeds": [{"table": "t"}], "masks": [{"name": "a", "columns": [["t","a"]]}, {"name": "b", "columns": [["t","b"]]}], "limits": {"cells": 3}}, "CELL_LIMIT")
        self.refusal({"seeds": [{"table": "t"}], "limits": {"steps": 1}}, "WORK_LIMIT")
        self.refusal({"seeds": [{"table": "t"}], "limits": {"query_rows": 1}, "queries": [{"name": "all", "sql": "SELECT a FROM t", "expect": [["a"],["b"]]}]}, "QUERY_LIMIT")
        self.refusal({"seeds": [{"table": "t"}], "queries": [{"name": "wide", "sql": "SELECT printf('%2000000s','x')", "expect": [["x"]]}]}, "CONSUMER_QUERY")

    def test_seed_and_query_are_read_only(self):
        self.database("CREATE TABLE t(a INTEGER); INSERT INTO t VALUES(1);")
        self.refusal({"seeds": [{"table": "t"}], "queries": [{"name": "delete", "sql": "DELETE FROM t RETURNING a", "expect": [[1]]}]}, "SQLITE")
        self.refusal({"seeds": [{"table": "t", "where": "load_extension('evil') IS NULL"}]}, "SQLITE")

    def test_virtual_generated_custom_collation(self):
        self.database("CREATE TABLE t(a INTEGER,b INTEGER GENERATED ALWAYS AS(a+1)); INSERT INTO t(a) VALUES(1);")
        self.refusal({"seeds": [{"table": "t"}]}, "UNSUPPORTED")
        self.source.unlink()
        with closing(sqlite3.connect(self.source)) as db, db:
            db.create_collation("custom", lambda a,b: (a>b)-(a<b))
            db.executescript("CREATE TABLE t(a TEXT COLLATE custom PRIMARY KEY); INSERT INTO t VALUES('a');")
        self.refusal({"seeds": [{"table": "t"}]}, "UNSUPPORTED")

    def test_wal_and_sidecar_refusal(self):
        self.database("CREATE TABLE t(a INTEGER); INSERT INTO t VALUES(1);")
        Path(str(self.source)+"-journal").write_bytes(b"sentinel")
        self.refusal({"seeds": [{"table": "t"}]}, "QUIESCENT")
        Path(str(self.source)+"-journal").unlink()
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("PRAGMA journal_mode=WAL")
        self.refusal({"seeds": [{"table": "t"}]}, "QUIESCENT")

    def test_blob_null_and_json_consumer_output(self):
        self.database("CREATE TABLE t(a BLOB UNIQUE); INSERT INTO t VALUES(X'0102'),(NULL);")
        report = weave(self.source, self.dest, {"seeds": [{"table": "t"}], "masks": [{"name": "id", "columns": [["t","a"]]}], "queries": [{"name": "type", "sql": "SELECT typeof(a),length(a) FROM t ORDER BY rowid", "expect": [["blob",16],["null",None]]}]})
        self.assertEqual(report["masked_classes"][0]["occurrences"], 1)
        other = self.root / "raw.db"
        with self.assertRaises(FixtureError) as error:
            weave(self.source, other, {"seeds": [{"table": "t"}], "queries": [{"name": "raw", "sql": "SELECT a FROM t", "expect": []}]})
        self.assertEqual(error.exception.code, "QUERY_VALUE")

    def test_similar_internal_prefix_user_table(self):
        self.database("CREATE TABLE sqliteXledger(id INTEGER PRIMARY KEY); INSERT INTO sqliteXledger VALUES(1);")
        report = weave(self.source, self.dest, {"seeds": [{"table": "sqliteXledger"}]})
        self.assertEqual(report["retained_rows"], {"sqliteXledger": 1})

    def test_determinism_and_unlinked_equal_values(self):
        self.database("CREATE TABLE t(id INTEGER PRIMARY KEY,other INTEGER); INSERT INTO t VALUES(1,1),(2,1);")
        plan = {"seeds": [{"table": "t"}], "masks": [{"name": "id", "columns": [["t","id"]]}]}
        first = weave(self.source, self.dest, plan)
        second = weave(self.source, self.root/"second.db", copy.deepcopy(plan))
        self.assertEqual(first["fixture_sha256"], second["fixture_sha256"])
        with closing(sqlite3.connect(self.dest)) as db:
            self.assertEqual(db.execute("SELECT DISTINCT other FROM t").fetchall(), [(1,)])

    def test_sqlite_recursive_cte_oracle_small_cyclic_graphs(self):
        rng = random.Random(184)
        # Independent oracle is a recursive SQLite set query; it does not call
        # private engine helpers or reproduce the Python closure algorithm.
        for case in range(32):
            source, destination = self.root/f"s{case}.db", self.root/f"d{case}.db"
            n = rng.randint(1,7)
            with closing(sqlite3.connect(source)) as db, db:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("CREATE TABLE n(id INTEGER PRIMARY KEY,parent INTEGER REFERENCES n(id) DEFERRABLE INITIALLY DEFERRED)")
                db.executemany("INSERT INTO n VALUES(?,?)", [(i, rng.choice([None]+list(range(1,n+1)))) for i in range(1,n+1)])
                db.commit()
                seed = rng.randint(1,n)
                oracle = db.execute("WITH RECURSIVE closure(id) AS (SELECT ? UNION SELECT n.parent FROM n JOIN closure ON n.id=closure.id WHERE n.parent IS NOT NULL) SELECT n.id,n.parent FROM n JOIN closure ON n.id=closure.id ORDER BY n.id", (seed,)).fetchall()
            before = source.read_bytes()
            report = weave(source, destination, {"seeds": [{"table": "n", "where": "id=?", "params": [seed]}]})
            with closing(sqlite3.connect(destination)) as db:
                self.assertEqual(db.execute("SELECT id,parent FROM n ORDER BY id").fetchall(), oracle)
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(report["retained_rows"]["n"], len(oracle))
            self.assertEqual(source.read_bytes(), before)

    def test_actual_registered_cli_malformed_duplicate_and_overflow(self):
        self.database("CREATE TABLE t(a INTEGER); INSERT INTO t VALUES(1);")
        executable = Path(sysconfig.get_path("scripts")) / ("fixtureweaver.exe" if os.name=="nt" else "fixtureweaver")
        inputs = ["{", '{"seeds":[],"seeds":[]}', '{"seeds":[{"table":"t"}],"salt":1e9999}', '{"seeds":[{"table":"t"}],"salt":'+"9"*5000+"}"]
        for text in inputs:
            plan = self.root / "plan.json"
            plan.write_text(text, encoding="utf-8")
            process = subprocess.run([str(executable),str(self.source),str(self.dest),"--plan",str(plan)], capture_output=True,text=True)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(json.loads(process.stderr)["error"]["code"], "PLAN")
            self.assertNotIn("Traceback", process.stderr)
        self.assertFalse(self.dest.exists())


if __name__ == "__main__":
    unittest.main()
