"""Validate direct-parent history; optionally replay every unchanged archive-wheel probe."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from archive_probe import ROOT, check_revision, sha256


def verify(records_only=False):
    rounds=json.loads((ROOT/"docs/history.json").read_text(encoding="utf-8"))
    for row in rounds:
        parent=subprocess.check_output(["git","rev-parse",row["after"]+"^"],cwd=ROOT,text=True).strip()
        if parent!=row["before"]:
            raise RuntimeError("Correction is not a direct-parent commit")
        # Git canonical blob hashing makes the check insensitive to a user's
        # checkout line-ending preference while the committed bytes stay fixed.
        probe_bytes=subprocess.check_output(["git","show","HEAD:"+row["probe"]],cwd=ROOT)
        if sha256(probe_bytes)!=row["probe_sha256"]:
            raise RuntimeError("Committed probe changed")
        with tempfile.TemporaryDirectory() as temporary:
            portable_probe=Path(temporary)/Path(row["probe"]).name
            portable_probe.write_bytes(probe_bytes)
            for kind,expected in (("before",1),("after",0)):
                path=ROOT/"docs/evidence/history"/(row[kind][:12]+"-"+Path(row["probe"]).stem+".json")
                record=json.loads(path.read_text(encoding="utf-8"))
                if record["revision"]!=row[kind] or record["probe_sha256"]!=row["probe_sha256"] or record["probe_exit"]!=expected or not record["archive_installed_source_bytes_equal"]:
                    raise RuntimeError("Historical receipt mismatch")
                if not records_only:
                    result=check_revision(row[kind],portable_probe,ROOT/".artifacts/history-replay",row["probe"])
                    if result["probe_exit"]!=expected or result["probe_sha256"]!=row["probe_sha256"]:
                        raise RuntimeError("Historical probe no longer reproduces")
        print(json.dumps({"round":row["round"],"direct_parent":True,"unchanged_probe":True,"before_exit":1,"after_exit":0,"replayed":not records_only}))
    return 0


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--records-only",action="store_true")
    args=parser.parse_args()
    raise SystemExit(verify(args.records_only))
