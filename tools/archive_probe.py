"""Install a normal wheel from an exact Git archive and run an unchanged probe.

No editable installs or source-tree import overrides. Paths are redacted in logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import venv


ROOT = Path(__file__).resolve().parents[1]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def capture(argv, cwd, log, redactions):
    result = subprocess.run([str(a) for a in argv], cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    raw = "$ " + " ".join(str(a) for a in argv) + "\n" + result.stdout + result.stderr
    for old, new in redactions:
        raw = raw.replace(str(old), new)
    raw = re.sub(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s]+", "<user>", raw, flags=re.IGNORECASE)
    raw = re.sub(r"/home/[^/\s]+", "<user>", raw)
    log.append(raw + f"\nexit={result.returncode}\n")
    return result


def check_revision(revision, probe, output_directory):
    sha = subprocess.check_output(["git", "rev-parse", revision], cwd=ROOT, text=True).strip()
    log = []
    probe = Path(probe).resolve()
    with tempfile.TemporaryDirectory(prefix="fixtureweaver-history-") as temporary:
        temporary = Path(temporary)
        archive, source, environment, wheels = temporary / "archive.tar", temporary / "source", temporary / "env", temporary / "wheels"
        source.mkdir()
        subprocess.run(["git", "archive", "--format=tar", "--output", str(archive), sha], cwd=ROOT, check=True)
        with tarfile.open(archive) as stream:
            # This archive is generated from our own Git tree. extract filter is portable on 3.11+.
            for member in stream.getmembers():
                target = (source / member.name).resolve()
                if not target.is_relative_to(source) or not member.isfile() and not member.isdir():
                    raise RuntimeError("Unsafe member in Git archive")
            stream.extractall(source)
        venv.create(environment, with_pip=True)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        redactions = [(temporary, "<history-temp>"), (ROOT, "<repo>"), (Path.home(), "<user>"), (sys.prefix, "<driver-python>")]
        build = capture([python, "-m", "pip", "wheel", source, "--no-deps", "--wheel-dir", wheels], source, log, redactions)
        if build.returncode:
            raise RuntimeError("Archive wheel build failed")
        wheel = next(wheels.glob("fixtureweaver-*.whl"))
        install = capture([python, "-m", "pip", "install", "--no-deps", wheel], temporary, log, redactions)
        if install.returncode:
            raise RuntimeError("Ordinary wheel install failed")
        receipt_code = "import fixtureweaver,pathlib,json,hashlib; p=pathlib.Path(fixtureweaver.__file__).parent; print(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.glob('*.py'))}))"
        receipt = capture([python, "-c", receipt_code], temporary, log, redactions)
        installed = json.loads(receipt.stdout)
        archived = {p.name: sha256(p.read_bytes()) for p in (source / "src/fixtureweaver").glob("*.py")}
        if installed != archived:
            raise RuntimeError("Installed bytes differ from exact archive")
        result = capture([python, probe], temporary, log, redactions)
        summary = {"revision": sha, "probe": str(probe.relative_to(ROOT)).replace("\\", "/"), "probe_sha256": sha256(probe.read_bytes()), "wheel_sha256": sha256(wheel.read_bytes()), "archive_installed_source_bytes_equal": True, "source_file_sha256": archived, "probe_exit": result.returncode, "probe_stdout": result.stdout.strip(), "probe_stderr": result.stderr.strip()}
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    prefix = output_directory / (sha[:12] + "-" + probe.stem)
    prefix.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    prefix.with_suffix(".log").write_text("\n".join(log), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("revision")
    parser.add_argument("probe")
    parser.add_argument("--out", default="docs/evidence/history")
    parser.add_argument("--expect-exit", type=int, default=0)
    args = parser.parse_args()
    observed = check_revision(args.revision, args.probe, ROOT / args.out)
    raise SystemExit(0 if observed["probe_exit"] == args.expect_exit else 1)
