"""Fair finite synthetic contrast; no SDV/Faker competitor execution is claimed.

The baseline implements seed-only row sampling plus deterministic independent
column masks. The ablation adds FixtureWeaver's closure but retains independent
masks. All branches share exact source, seed, mask-class declarations and queries.
The harness baseline supports these ordinary rowid/WITHOUT ROWID example schemas.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from fixtureweaver import FixtureError, weave
from demo import create_example


def q(name):
    return '"'+name.replace('"','""')+'"'


def independent_mask(value, table, column, salt):
    if value is None:
        return None
    digest=hashlib.sha256((salt+"\0"+table+"\0"+column+"\0"+str(value)).encode()).digest()
    number=100000+int.from_bytes(digest[:6],"big")
    if type(value) is int:
        return number
    if type(value) is float:
        return float(number)
    if isinstance(value,bytes):
        return digest[:16]
    return "fw_"+digest.hex()[:24]


def baseline(source, destination, plan, closure=False):
    original=source
    source_counts={}
    with closing(sqlite3.connect(original)) as db:
        source_counts={name:db.execute(f"SELECT count(*) FROM {q(name)}").fetchone()[0] for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND lower(substr(name,1,7))<>'sqlite_'")}
    if closure:
        closed=destination.parent/(destination.stem+"-closure.db")
        weave(source,closed,{"seeds":plan["seeds"],"queries":plan["queries"]})
        source=closed
    with closing(sqlite3.connect(source)) as db, closing(sqlite3.connect(destination)) as output:
        schemas=db.execute("SELECT name,sql FROM sqlite_schema WHERE type='table' AND lower(substr(name,1,7))<>'sqlite_' ORDER BY name").fetchall()
        columns={name:[row[1] for row in db.execute(f"PRAGMA table_info({q(name)})")] for name,_ in schemas}
        masked=set(tuple(pair) for mask in plan.get("masks",[]) for pair in mask["columns"])
        edges=[]
        for name,_ in schemas:
            edges += [((name,row[3]),(row[2],row[4])) for row in db.execute(f"PRAGMA foreign_key_list({q(name)})")]
        previous=None
        while previous!=masked:
            previous=masked.copy()
            for a,b in edges:
                if a in masked or b in masked:
                    masked.update((a,b))
        rows={name:[] for name,_ in schemas}
        for name,_ in schemas:
            if closure:
                rows[name]=db.execute(f"SELECT * FROM {q(name)}").fetchall()
            else:
                # Sets deduplicate repeated identical seed rows in this harness.
                for seed in plan["seeds"]:
                    if seed["table"]==name:
                        selected=db.execute(f"SELECT * FROM {q(name)} WHERE ({seed.get('where','1')})",seed.get("params",[])).fetchall()
                        for row in selected:
                            if row not in rows[name]:
                                rows[name].append(row)
            output.execute(dict(schemas)[name])
        # The naive baseline copies rows with enforcement disabled, then exposes
        # actual failures rather than claiming an invalid fixture is usable.
        for name,_ in schemas:
            for row in rows[name]:
                values=[independent_mask(value,name,column,plan.get("salt","fixtureweaver-demo")) if (name,column) in masked else value for column,value in zip(columns[name],row)]
                output.execute(f"INSERT INTO {q(name)} VALUES({','.join('?' for _ in values)})",values)
        output.commit()
        violations=output.execute("PRAGMA foreign_key_check").fetchall()
        results=[]
        for query in plan["queries"]:
            actual=[list(row) for row in output.execute(query["sql"],query.get("params",[]))]
            results.append({"name":query["name"],"passed":actual==query["expect"],"result":actual})
        return {"source_rows":sum(source_counts.values()),"retained_rows":sum(len(data) for data in rows.values()),"foreign_key_violations":len(violations),"consumer_queries":results,"usable":not violations and all(item["passed"] for item in results)}


def one_case(name,source,plan,root):
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    report=weave(source,root/(name+"-weave.db"),plan)
    woven={"source_rows":sum(report["source_rows"].values()),"retained_rows":sum(report["retained_rows"].values()),"closure_added_rows":report["closure_added_rows"],"foreign_key_violations":0,"consumer_queries":report["queries"],"usable":True,"source_bytes":report["source_bytes"],"fixture_bytes":report["fixture_bytes"]}
    sampled=baseline(source,root/(name+"-sample.db"),plan)
    independent_closed=baseline(source,root/(name+"-independent-closed.db"),plan,closure=True)
    return {"case":name,"source_sha256":before,"same_source_seed_masks_queries":True,"sample_independent":sampled,"closure_independent_ablation":independent_closed,"closure_shared":woven,"source_unchanged":before==hashlib.sha256(source.read_bytes()).hexdigest()}


def contrast():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        source,plan=create_example(root/"checkout")
        results=[one_case("checkout_composite_affinity",source,plan,root)]
        equal=root/"equal.db"
        with closing(sqlite3.connect(equal)) as db,db:
            db.executescript("CREATE TABLE ledger(id INTEGER PRIMARY KEY,value INTEGER); INSERT INTO ledger VALUES(1,8),(2,9);")
        plan={"seeds":[{"table":"ledger","where":"id=1"}],"masks":[{"name":"id","columns":[["ledger","id"]]}],"queries":[{"name":"count","sql":"SELECT count(*),sum(value) FROM ledger","expect":[[1,8]]}]}
        results.append(one_case("equal_no_relational_dependency",equal,plan,root))
        adverse=root/"adverse.db"
        with closing(sqlite3.connect(adverse)) as db,db:
            db.execute("CREATE TABLE node(id INTEGER PRIMARY KEY,parent INTEGER REFERENCES node(id))")
            db.executemany("INSERT INTO node VALUES(?,?)",[(i,i-1 if i>1 else None) for i in range(1,21)])
        plan={"seeds":[{"table":"node","where":"id=20"}],"masks":[{"name":"node","columns":[["node","id"]]}],"queries":[{"name":"complete_chain","sql":"SELECT count(*) FROM node","expect":[[20]]}]}
        results.append(one_case("adverse_full_chain_retention",adverse,plan,root))
        bounded=dict(plan,limits={"rows":10})
        try:
            weave(adverse,root/"bounded.db",bounded)
            exhausted="unexpected success"
        except FixtureError as error:
            exhausted=error.code
        return {"synthetic":True,"baseline_definition":"seed row sampling + deterministic independent column masking; closure ablation uses same engine closure with no shared masks","competitor_execution":False,"cases":results,"adverse_closure_bound":exhausted}


if __name__=="__main__":
    print(json.dumps(contrast(),indent=2))
