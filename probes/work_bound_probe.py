"""A tiny VM budget must cover many short SQLite statements as well as long SQL."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from fixtureweaver import FixtureError, weave


def run():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source, destination = root / "s.db", root / "d.db"
        with closing(sqlite3.connect(source)) as db, db:
            db.executescript("CREATE TABLE t(a INTEGER); INSERT INTO t VALUES(1);")
        before = source.read_bytes()
        try:
            report = weave(source, destination, {"seeds": [{"table": "t"}], "limits": {"steps": 1}})
            print(json.dumps({"probe": "cumulative_vm_budget", "passed": False, "unexpected_success": report.get("vm_steps_upper_counter")}))
            return 1
        except FixtureError as error:
            passed = error.code == "WORK_LIMIT" and source.read_bytes() == before and not destination.exists()
            print(json.dumps({"probe": "cumulative_vm_budget", "passed": passed, "error": error.code, "source_unchanged": source.read_bytes()==before, "no_destination": not destination.exists()}))
            return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(run())
