"""An integral REAL mask must not be converted to INTEGER by NUMERIC affinity."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from fixtureweaver import FixtureError, weave


def run():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        source,destination=root/"s.db",root/"d.db"
        with closing(sqlite3.connect(source)) as db,db:
            db.executescript("CREATE TABLE p(id NUMERIC UNIQUE); CREATE TABLE c(id INTEGER PRIMARY KEY,p TEXT REFERENCES p(id)); INSERT INTO p VALUES(1.5); INSERT INTO c VALUES(1,'1.50');")
        before=source.read_bytes()
        plan={"seeds":[{"table":"c"}],"masks":[{"name":"id","columns":[["p","id"]]}],"queries":[{"name":"storage","sql":"SELECT typeof(p.id),typeof(c.p),count(*) FROM c JOIN p ON p.id=c.p","expect":[["real","text",1]]}]}
        try:
            report=weave(source,destination,plan)
        except FixtureError as error:
            print(json.dumps({"probe":"numeric_real_storage","passed":False,"error":error.as_dict()}))
            return 1
        passed=source.read_bytes()==before
        print(json.dumps({"probe":"numeric_real_storage","passed":passed,"result":report["queries"][0]["result"],"source_unchanged":passed}))
        return 0 if passed else 1


if __name__=="__main__":
    raise SystemExit(run())
