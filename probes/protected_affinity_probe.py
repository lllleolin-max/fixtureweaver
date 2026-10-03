"""A protected TEXT '1.0' pins an INTEGER-linked identity under SQLite equality."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from fixtureweaver import FixtureError, weave


def run():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source, destination = root / "source.db", root / "fixture.db"
        with closing(sqlite3.connect(source)) as db, db:
            db.executescript("PRAGMA foreign_keys=ON; CREATE TABLE p(id INTEGER PRIMARY KEY); CREATE TABLE c(id INTEGER PRIMARY KEY,p TEXT REFERENCES p(id)); INSERT INTO p VALUES(1),(2); INSERT INTO c VALUES(7,'1.0'),(8,'2');")
        plan = {"seeds": [{"table": "c", "where": "id=7"}], "masks": [{"name": "parent", "columns": [["p", "id"]]}], "protect": [{"table": "c", "column": "p"}], "queries": [{"name": "protected_identity", "sql": "SELECT p.id,c.p,typeof(p.id),typeof(c.p) FROM c JOIN p ON p.id=c.p", "expect": [[1,"1.0","integer","text"]]}]}
        try:
            report = weave(source, destination, plan)
        except FixtureError as error:
            print(json.dumps({"probe": "protected_affinity", "passed": False, "error": error.as_dict()}))
            return 1
        assert report["source_unchanged"]
        print(json.dumps({"probe": "protected_affinity", "passed": True, "result": report["queries"][0]["result"]}))
        return 0


if __name__ == "__main__":
    raise SystemExit(run())
