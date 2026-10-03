"""Synthetic checkout fixture, installed SDK and actual registered CLI."""
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sysconfig
import tempfile

from fixtureweaver import weave


def create_example(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source = root / "checkout.db"
    if source.exists():
        raise ValueError("Demo source already exists; choose a new --out directory")
    with closing(sqlite3.connect(source)) as db, db:
        db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE tenant(code TEXT COLLATE NOCASE PRIMARY KEY);
        CREATE TABLE account(tenant TEXT COLLATE NOCASE REFERENCES tenant(code),
          id INTEGER,name TEXT NOT NULL,PRIMARY KEY(tenant,id)) WITHOUT ROWID;
        CREATE TABLE orders(id INTEGER PRIMARY KEY,tenant TEXT,account TEXT,
          amount INTEGER CHECK(amount>=0),
          FOREIGN KEY(tenant,account) REFERENCES account(tenant,id));
        CREATE TABLE line(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES orders(id),
          sku TEXT,quantity INTEGER CHECK(quantity>0));
        INSERT INTO tenant VALUES('ACME'),('BETA');
        INSERT INTO account VALUES('ACME',1,'Synthetic Alice'),('ACME',2,'Synthetic Bob'),('BETA',1,'Synthetic Casey');
        INSERT INTO orders VALUES(101,'acme','01',120),(102,'ACME','2',90),
          (103,'BETA','1',40),(104,'ACME','1',12),(105,'BETA','1',55);
        INSERT INTO line VALUES(1,101,'widget',1),(2,101,'book',2),
          (3,102,'pen',3),(4,103,'book',1),(5,104,'pen',1),(6,105,'widget',1);
        """)
    plan = {"salt": "synthetic-checkout-v1", "seeds": [{"table": "line", "where": "id IN (?,?)", "params": [1,2]}], "masks": [{"name": "tenant", "columns": [["tenant","code"]]}, {"name": "account", "columns": [["account","id"]]}, {"name": "order", "columns": [["orders","id"]]}, {"name": "name", "columns": [["account","name"]]}], "queries": [{"name": "checkout", "sql": "SELECT orders.amount,sum(line.quantity),count(*) FROM line JOIN orders ON orders.id=line.order_id JOIN account ON account.tenant=orders.tenant AND account.id=orders.account JOIN tenant ON tenant.code=account.tenant GROUP BY orders.amount", "expect": [[120,3,2]]}]}
    (root / "plan.json").write_text(json.dumps(plan, indent=2)+"\n", encoding="utf-8")
    return source, plan


def demonstrate(root):
    source, plan = create_example(root)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    sdk = weave(source, Path(root)/"sdk-fixture.db", plan)
    executable = Path(sysconfig.get_path("scripts")) / ("fixtureweaver.exe" if os.name=="nt" else "fixtureweaver")
    process = subprocess.run([str(executable),str(source),str(Path(root)/"cli-fixture.db"),"--plan",str(Path(root)/"plan.json")],text=True,capture_output=True)
    if process.returncode:
        raise RuntimeError(process.stderr)
    cli = json.loads(process.stdout)["report"]
    result = {"synthetic": True,"sdk_retained_rows": sdk["retained_rows"], "source_total_rows": sum(sdk["source_rows"].values()), "fixture_total_rows": sum(sdk["retained_rows"].values()), "closure_added_rows": sdk["closure_added_rows"], "consumer_results": sdk["queries"], "actual_registered_cli_exit": process.returncode,"same_sdk_cli_database_hash": sdk["fixture_sha256"]==cli["fixture_sha256"], "source_sha256_before": before,"source_sha256_after": hashlib.sha256(source.read_bytes()).hexdigest(),"source_unchanged": before == hashlib.sha256(source.read_bytes()).hexdigest()}
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out")
    args=parser.parse_args()
    if args.out:
        result=demonstrate(Path(args.out))
    else:
        with tempfile.TemporaryDirectory() as directory:
            result=demonstrate(Path(directory))
    print(json.dumps(result,indent=2))
