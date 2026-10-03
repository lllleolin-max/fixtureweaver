# Real correction history

Observed locally on Windows, Python 3.14.3, SQLite 3.50.4, 2026-10-03. Initial implementation is `9b74f497c85e3e3ad34927a3bbd5796fb896cd03`. These rounds are post-initial defect discoveries and **separate direct-parent code corrections**, not a commit/feature count. Each identical portable probe was executed against a normally built and installed wheel from the exact before and after Git archives. No editable install or `PYTHONPATH` was used.

`tools/archive_probe.py` creates a fresh archive and virtual environment per revision, runs ordinary `pip wheel`/`pip install`, compares installed package bytes with archive files, executes the same external probe, and saves actual stdout/exit/build logs. Tracked logs redact local host paths. Wheel ZIP hashes can vary across rebuilds; the archived/installed Python byte equality is checked each time. `docs/history.json` fixes probe hashes and SHAs. `python tools/verify_history.py` verifies direct parents/probe bytes and replays all ten installs; `--records-only` checks saved receipts without rerunning.

## Round 1: implicit rowid consumer changed

- Before: `9b74f497c85e3e3ad34927a3bbd5796fb896cd03`.
- Discovered defect: a retained row with TEXT primary key and implicit `rowid=42` was inserted with a fresh implicit `rowid=1`. A legitimate declared rowid consumer therefore failed even though named values/FKs were valid.
- Correction: `41e1c6c077f9eeea8da481133d0955beae47bb7a` preserves independent implicit rowids. PK-index inspection distinguishes INTEGER PRIMARY KEY aliases, including the INTEGER PRIMARY KEY DESC exception, so masked aliased keys can still set their new rowids.
- Unchanged probe: [`rowid_probe.py`](../probes/rowid_probe.py), SHA-256 `4a7578e8ba1e5443389a4eb5af5c36292aff34230dd04003c5362e15e3f2dad5`.
- Actual before result: exit 1, `CONSUMER_QUERY`, expected `[[42,"retained"]]`, actual `[[1,"retained"]]`. [Receipt](evidence/history/9b74f497c85e-rowid_probe.json), [log](evidence/history/9b74f497c85e-rowid_probe.log).
- Actual after result: exit 0, `[[42,"retained"]]`. [Receipt](evidence/history/41e1c6c077f9-rowid_probe.json), [log](evidence/history/41e1c6c077f9-rowid_probe.log).

```sh
python tools/archive_probe.py 9b74f497c85e3e3ad34927a3bbd5796fb896cd03 probes/rowid_probe.py --expect-exit 1
python tools/archive_probe.py 41e1c6c077f9eeea8da481133d0955beae47bb7a probes/rowid_probe.py
```

Remaining boundary: a masked INTEGER PRIMARY KEY intentionally changes its aliased rowid. This does not preserve undeclared insert history or source autoincrement high-water marks.

## Round 2: Python conversion rejected SQLite-compatible protection

- Before: `41e1c6c077f9eeea8da481133d0955beae47bb7a`.
- Discovered defect: protected TEXT child `"1.0"` legally references INTEGER parent `1`, but coercing the protected spelling with Python `int('1.0')` raised an avoidable conflict. Python casts are not SQLite affinity.
- Correction: `3e691cc99089091e7d19ab4377ec9893c7eb4e51` pins the full SQLite-equivalent group, retaining each original storage representation, and reports pinned-group count. It also avoids REAL-to-INTEGER truncation at this boundary.
- Unchanged probe: [`protected_affinity_probe.py`](../probes/protected_affinity_probe.py), SHA-256 `2f464871c8c89f1e58395d0a18a71e6bf110f5d4ee554239823cb55060913548`.
- Before: exit 1, `PROTECTED_CONFLICT`. [Receipt](evidence/history/41e1c6c077f9-protected_affinity_probe.json), [log](evidence/history/41e1c6c077f9-protected_affinity_probe.log).
- After: exit 0, actual joined result `[[1,"1.0","integer","text"]]`. [Receipt](evidence/history/3e691cc99089-protected_affinity_probe.json), [log](evidence/history/3e691cc99089-protected_affinity_probe.log).

```sh
python tools/archive_probe.py 41e1c6c077f9eeea8da481133d0955beae47bb7a probes/protected_affinity_probe.py --expect-exit 1
python tools/archive_probe.py 3e691cc99089091e7d19ab4377ec9893c7eb4e51 probes/protected_affinity_probe.py
```

Remaining boundary: pinning exposes the original linked identity; this is explicit protection behavior, not a privacy-preserving exception. Colliding candidate tokens and incompatible class domains still need actual constraint refusal.

## Round 3: adversarial scalar exceptions escaped the interfaces

- Before: `3e691cc99089091e7d19ab4377ec9893c7eb4e51`.
- Discovery cue: independent portfolio coordination raised parser/typed-scalar failures in another project; this project's own console and SQLite mask boundary were tested independently. A 5,000-digit integer caused the registered CLI to exit 1 with a traceback. A legal SQLite stored infinity reached typed identity serialization before finite-value validation, escaping SDK `ValueError`.
- Correction: `76b4125ecf023305d6f173f14d0d123b9863f701` bounds parsed INTEGERs to SQLite signed 64 bits, rejects overflowing REAL JSON, limits CLI plan size, normalizes malformed/nested plan errors, validates SDK scalar trees, and rejects nonfinite stored identifiers before encoding.
- Unchanged probe: [`scalar_probe.py`](../probes/scalar_probe.py), SHA-256 `1a1cf2ea62b29bf903fada6c69b7a5669798e122ee5f27fc0216f79567b60c4e`.
- Before: probe exit 1; actual console exit 1/traceback, SDK escaped `ValueError`. Source unchanged and no destination in both paths. [Receipt](evidence/history/3e691cc99089-scalar_probe.json), [log](evidence/history/3e691cc99089-scalar_probe.log).
- After: probe exit 0; actual console exit 2/structured `PLAN`, SDK `MASK_TYPE`, unchanged source/no destination. [Receipt](evidence/history/76b4125ecf02-scalar_probe.json), [log](evidence/history/76b4125ecf02-scalar_probe.log).

```sh
python tools/archive_probe.py 3e691cc99089091e7d19ab4377ec9893c7eb4e51 probes/scalar_probe.py --expect-exit 1
python tools/archive_probe.py 76b4125ecf023305d6f173f14d0d123b9863f701 probes/scalar_probe.py
```

Remaining boundary: nonfinite identifiers and nonfinite/BLOB raw consumer outputs are refused; use `hex()` for BLOB queries. The source can contain an unmasked infinity if no consumer query requires emitting it, but masking it is unsupported.

## Round 4: short SQLite statements escaped the cumulative work budget

- Before: `76b4125ecf023305d6f173f14d0d123b9863f701`.
- Discovered defect during expanded adversarial checks: SQLite progress callbacks every 100 instructions did not fire across many individually short statements. A plan requesting only one instruction unexpectedly succeeded with counter zero.
- Correction: `2c64ce94ce4f090262d5da84b25c7b55750412e5` counts progress callbacks at interval 1 across managed source/schema-clone/output work. It also makes the masked-cell cap aggregate, applies SQLite length/SQL/attachment limits, preserves valid user table names resembling `sqlite_`, and keeps consumer results JSON-safe.
- Unchanged probe: [`work_bound_probe.py`](../probes/work_bound_probe.py), SHA-256 `56e29fce539663ee3f176f08f660843c22dcfe29526bb76af56928743c4b80bf`.
- Before: exit 1, unexpected successful output, counter 0. [Receipt](evidence/history/76b4125ecf02-work_bound_probe.json), [log](evidence/history/76b4125ecf02-work_bound_probe.log).
- After: exit 0, `WORK_LIMIT`, unchanged source/no destination. [Receipt](evidence/history/2c64ce94ce4f-work_bound_probe.json), [log](evidence/history/2c64ce94ce4f-work_bound_probe.log).

```sh
python tools/archive_probe.py 76b4125ecf023305d6f173f14d0d123b9863f701 probes/work_bound_probe.py --expect-exit 1
python tools/archive_probe.py 2c64ce94ce4f090262d5da84b25c7b55750412e5 probes/work_bound_probe.py
```

Remaining boundary: this counts observed SQLite VM progress instructions, not CPU time/file IO/Python work/all native internals. Setup pragmas and hashing remain outside the managed instruction budget.

## Round 5: NUMERIC affinity changed REAL token storage

- Before: `4bfbfadd19bdeef6537005befa020aca97095fad`.
- Discovered defect: replacing NUMERIC REAL `1.5` with an integral Python float let SQLite affinity store INTEGER instead. FKs still passed, but the declared `typeof()` consumer changed. Correct Python output types alone were insufficient.
- Correction: `ab731fd039cd65a83b035e10e9964fec2ee82b8b` uses exactly representable quarter-fraction tokens for REAL-only groups and executes `INSERT ... RETURNING typeof(...)` to verify every inserted column's actual storage class against the original. Mixed INTEGER/REAL groups retain integral tokens where original receiving domains already preserve their different types, otherwise refuse a witnessed `MASK_TYPE`.
- Unchanged probe: [`storage_type_probe.py`](../probes/storage_type_probe.py), SHA-256 `4240d0abc0699c4585c2d059d9786aae501dcdc42979a5e53d499d44bb6b4f1c`.
- Before: exit 1, `CONSUMER_QUERY`, expected `[["real","text",1]]`, actual `[["integer","text",1]]`. [Receipt](evidence/history/4bfbfadd19bd-storage_type_probe.json), [log](evidence/history/4bfbfadd19bd-storage_type_probe.log).
- After: exit 0, `[["real","text",1]]`, unchanged source. [Receipt](evidence/history/ab731fd039cd-storage_type_probe.json), [log](evidence/history/ab731fd039cd-storage_type_probe.log).

```sh
python tools/archive_probe.py 4bfbfadd19bdeef6537005befa020aca97095fad probes/storage_type_probe.py --expect-exit 1
python tools/archive_probe.py ab731fd039cd65a83b035e10e9964fec2ee82b8b probes/storage_type_probe.py
```

Remaining boundary: schema CHECK/UNIQUE constraints can reject tokens; this preserves accepted storage classes, not all business meanings. The mask engine is not an arbitrary constraint solver.

## Full-suite release evidence and honest scope

The first full archived suite at `2c64ce9` found a test-harness expectation error: SQLite's bounded `printf` returned NULL, leading to `CONSUMER_QUERY`, rather than throwing the test's expected native error. A helper also shadowed `unittest.TestCase.fail`, obscuring the assertion. `4bfbfadd19bdeef6537005befa020aca97095fad` fixes that harness expectation/name and adds cross-platform/replay configuration. It is **not counted as another defect-correction iteration**.

The full suite was actually run from archive `4bfbfadd19bdeef6537005befa020aca97095fad`: **25 tests passed**, including 32 CTE-oracle graphs within one test. The receipt does not attribute those later tests to earlier SHAs. SDK and actual registered console both succeeded, with matching fixture hash and byte-preserved source. Checkout 16→5 rows passed query `[[120,3,2]]`; independent sampling retained 2 invalid rows, closure/independent retained 5 invalid rows. Equal and adverse cases remain. [Full receipt](evidence/release/4bfbfadd19bd.json), [actual log](evidence/release/4bfbfadd19bd.log).

Subsequent documentation/evidence commits are not extra iterations. Always use `python tools/verify_release.py <exact-sha> --out .artifacts/final` for a fresh final archive verification. Remote Ubuntu/Windows CI is not claimed by local receipts. No privacy proof, customers, revenue, production savings or self-awarded rubric pass is asserted.

After round 5, an ordinary wheel from archive `ab731fd039cd65a83b035e10e9964fec2ee82b8b` passed **26 tests** and all five portable probes, SDK, actual registered console and fair contrast. [Updated receipt](evidence/release/ab731fd039cd.json), [actual log](evidence/release/ab731fd039cd.log). The earlier 25-test statement remains attached solely to its earlier archive.
