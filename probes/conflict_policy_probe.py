"""Schema REPLACE must not silently delete retained rows when masks collide."""
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
            db.executescript("CREATE TABLE p(a TEXT UNIQUE ON CONFLICT REPLACE); CREATE TABLE q(b TEXT COLLATE NOCASE); INSERT INTO p VALUES('A'),('a'); INSERT INTO q VALUES('A');")
        before=source.read_bytes()
        plan={"seeds":[{"table":"p"},{"table":"q"}],"masks":[{"name":"id","columns":[["p","a"],["q","b"]]}]}
        try:
            report=weave(source,destination,plan)
            with closing(sqlite3.connect(destination)) as db:
                actual=db.execute("SELECT count(*) FROM p").fetchone()[0]
            print(json.dumps({"probe":"schema_conflict_policy","passed":False,"reported_retained":report["retained_rows"]["p"],"actual_retained":actual,"source_unchanged":before==source.read_bytes()}))
            return 1
        except FixtureError as error:
            passed=error.code=="MASK_CONSTRAINT" and not destination.exists() and before==source.read_bytes()
            print(json.dumps({"probe":"schema_conflict_policy","passed":passed,"error":error.code,"no_destination":not destination.exists(),"source_unchanged":before==source.read_bytes()}))
            return 0 if passed else 1


if __name__=="__main__":
    raise SystemExit(run())
