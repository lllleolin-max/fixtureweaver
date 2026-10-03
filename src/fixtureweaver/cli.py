from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .engine import FixtureError, weave


def load_plan(path: str) -> dict:
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise FixtureError("PLAN", "Duplicate JSON object key", key=key)
            result[key] = value
        return result
    def no_constant(value):
        raise FixtureError("PLAN", "Nonfinite JSON number", value=value)
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=no_duplicates, parse_constant=no_constant)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create a reduced SQLite fixture and validate its consumer queries")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--plan", required=True)
    args = parser.parse_args(argv)
    try:
        result = weave(args.source, args.destination, load_plan(args.plan))
    except FixtureError as error:
        print(json.dumps({"ok": False, "error": error.as_dict()}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": {"code": "PLAN_IO", "message": str(error)}}), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "report": result}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
