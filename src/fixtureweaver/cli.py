from __future__ import annotations

import argparse
import json
import math
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
    def bounded_integer(value):
        if len(value.lstrip("-")) > 19:
            raise FixtureError("PLAN", "JSON integers must fit SQLite signed 64-bit storage")
        parsed = int(value)
        if not -(2 ** 63) <= parsed < 2 ** 63:
            raise FixtureError("PLAN", "JSON integers must fit SQLite signed 64-bit storage")
        return parsed
    def finite_real(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise FixtureError("PLAN", "JSON REAL numbers must be finite")
        return parsed
    plan_path = Path(path)
    if plan_path.stat().st_size > 1024 * 1024:
        raise FixtureError("PLAN", "JSON plan exceeds 1 MiB input budget")
    try:
        return json.loads(plan_path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates, parse_constant=no_constant, parse_int=bounded_integer, parse_float=finite_real)
    except FixtureError:
        raise
    except (ValueError, RecursionError) as error:
        raise FixtureError("PLAN", "Malformed or excessively nested JSON plan") from error


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
