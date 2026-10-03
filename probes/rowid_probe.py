"""Portable consumer regression: implicit rowid must survive reduction."""
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
            db.executescript("CREATE TABLE item(code TEXT PRIMARY KEY, value TEXT); INSERT INTO item(rowid,code,value) VALUES(42,'alpha','retained'),(73,'beta','dropped');")
        plan = {"seeds": [{"table": "item", "where": "code='alpha'"}], "queries": [{"name": "rowid_consumer", "sql": "SELECT rowid,value FROM item", "expect": [[42, "retained"]]}]}
        try:
            report = weave(source, destination, plan)
        except FixtureError as error:
            print(json.dumps({"probe": "rowid_consumer", "passed": False, "error": error.as_dict()}))
            return 1
        assert report["retained_rows"] == {"item": 1}
        print(json.dumps({"probe": "rowid_consumer", "passed": True, "result": report["queries"][0]["result"]}))
        return 0


if __name__ == "__main__":
    raise SystemExit(run())
