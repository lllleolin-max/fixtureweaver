"""Registered CLI huge JSON integer and SDK stored infinity must refuse cleanly."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sysconfig
import tempfile
from fixtureweaver import FixtureError, weave


def run():
    observed = {}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source, destination, plan_path = root / "source.db", root / "fixture.db", root / "plan.json"
        with closing(sqlite3.connect(source)) as db, db:
            db.execute("CREATE TABLE p(id REAL UNIQUE)")
            db.execute("INSERT INTO p VALUES(?)", (float("inf"),))
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        plan_path.write_text('{"seeds":[{"table":"p","where":"id=?","params":[' + "9" * 5000 + "]}]}", encoding="utf-8")
        executable = Path(sysconfig.get_path("scripts")) / ("fixtureweaver.exe" if os.name == "nt" else "fixtureweaver")
        process = subprocess.run([str(executable), str(source), str(destination), "--plan", str(plan_path)], text=True, capture_output=True)
        try:
            response = json.loads(process.stderr)
            cli_passed = process.returncode == 2 and response["error"]["code"] == "PLAN"
        except (ValueError, KeyError, TypeError):
            cli_passed = False
        observed["cli"] = {"passed": cli_passed, "exit": process.returncode, "traceback_present": "Traceback" in process.stderr}
        try:
            weave(source, destination, {"seeds": [{"table": "p"}], "masks": [{"name": "id", "columns": [["p", "id"]]}]})
            observed["sdk"] = {"passed": False, "error": "unexpected success"}
        except FixtureError as error:
            observed["sdk"] = {"passed": error.code == "MASK_TYPE", "code": error.code}
        except Exception as error:
            observed["sdk"] = {"passed": False, "escaped_exception": type(error).__name__}
        observed["source_unchanged"] = before == hashlib.sha256(source.read_bytes()).hexdigest()
        observed["no_destination"] = not destination.exists()
    passed = observed["cli"]["passed"] and observed["sdk"]["passed"] and observed["source_unchanged"] and observed["no_destination"]
    print(json.dumps({"probe": "adversarial_scalars", "passed": passed, "observed": observed}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(run())
