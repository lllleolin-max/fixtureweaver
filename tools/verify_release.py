"""Fresh exact-archive NORMAL wheel; full archived tests, SDK, registered CLI, contrast."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import venv

from archive_probe import ROOT, capture, sha256


def verify(revision):
    sha=subprocess.check_output(["git","rev-parse",revision],cwd=ROOT,text=True).strip()
    log=[]
    with tempfile.TemporaryDirectory(prefix="fixtureweaver-release-") as temporary:
        temporary=Path(temporary)
        archive,source,environment,wheels=temporary/"source.tar",temporary/"source",temporary/"env",temporary/"wheels"
        source.mkdir()
        subprocess.run(["git","archive","--format=tar","--output",str(archive),sha],cwd=ROOT,check=True)
        with tarfile.open(archive) as stream:
            for member in stream.getmembers():
                if not (source/member.name).resolve().is_relative_to(source) or not member.isfile() and not member.isdir():
                    raise RuntimeError("Unsafe Git archive member")
            stream.extractall(source)
        venv.create(environment,with_pip=True)
        python=environment/("Scripts/python.exe" if os.name=="nt" else "bin/python")
        redactions=[(temporary,"<release-temp>"),(ROOT,"<repo>"),(Path.home(),"<user>"),(sys.prefix,"<driver-python>")]
        for argv in ([python,"-m","pip","wheel",source,"--no-deps","--wheel-dir",wheels],):
            if capture(argv,source,log,redactions).returncode:
                raise RuntimeError("Normal archive wheel build failed")
        wheel=next(wheels.glob("fixtureweaver-*.whl"))
        if capture([python,"-m","pip","install","--no-deps",wheel],temporary,log,redactions).returncode:
            raise RuntimeError("Ordinary wheel installation failed")
        code="import fixtureweaver,pathlib,hashlib,json,sys,sqlite3,sysconfig; p=pathlib.Path(fixtureweaver.__file__).parent; print(json.dumps({'files':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.glob('*.py'))},'python':sys.version.split()[0],'sqlite':sqlite3.sqlite_version,'scripts_path_is_same_environment':pathlib.Path(sysconfig.get_path('scripts')).parent==pathlib.Path(sys.prefix)}))"
        receipt=json.loads(capture([python,"-c",code],temporary,log,redactions).stdout)
        archived={p.name:sha256(p.read_bytes()) for p in (source/"src/fixtureweaver").glob("*.py")}
        if receipt["files"]!=archived:
            raise RuntimeError("Installed code differs from archive")
        tests=capture([python,"-m","unittest","discover","-s",source/"tests","-v"],temporary,log,redactions)
        if tests.returncode:
            raise RuntimeError("Archived full suite failed: "+tests.stderr[-1500:])
        demonstration=capture([python,source/"examples/demo.py"],temporary,log,redactions)
        contrast=capture([python,source/"examples/contrast.py"],temporary,log,redactions)
        if demonstration.returncode or contrast.returncode:
            raise RuntimeError("SDK/registered CLI/contrast failed")
        probes={}
        for path in sorted((source/"probes").glob("*_probe.py")):
            process=capture([python,path],temporary,log,redactions)
            if process.returncode:
                raise RuntimeError("Final probe failed: "+path.name)
            probes[path.name]=json.loads(process.stdout)
        summary={"revision":sha,"environment":{"os":os.name,"python":receipt["python"],"sqlite":receipt["sqlite"]},"normal_archive_wheel":True,"archive_installed_source_bytes_equal":True,"source_file_sha256":archived,"wheel_sha256":sha256(wheel.read_bytes()),"test_exit":tests.returncode,"archived_test_summary":[line for line in tests.stderr.splitlines() if line.startswith('Ran ') or line=='OK'],"sdk_and_registered_cli":json.loads(demonstration.stdout),"contrast":json.loads(contrast.stdout),"probes":probes}
    destination=ROOT/"docs/evidence/release"
    destination.mkdir(parents=True,exist_ok=True)
    (destination/(sha[:12]+".json")).write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    (destination/(sha[:12]+".log")).write_text("\n".join(log),encoding="utf-8")
    print(json.dumps(summary,indent=2))
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("revision",nargs="?",default="HEAD")
    args=parser.parse_args()
    verify(args.revision)
