# Bounded pilot rationale

Prospective users are application/QA engineers maintaining SQLite integration tests; a possible buyer is their platform/quality lead. Their job is reproducing a relational bug in a small fixture with keys that still connect after replacement. No buyer interview, customer, adoption, willingness-to-pay or revenue evidence exists.

The measured synthetic workflow selects two checkout lines from 16 rows. Closure adds three rows; shared masks yield a five-row fixture passing the checkout query. Sampling fails two FKs; closure with independent masks retains five rows but fails four FKs. This demonstrates usefulness, not engineer-time savings. The tiny DB remains 24,576 bytes. A 20-row chain requires every row, and a ten-row closure cap refuses it.

A pilot can use 5–10 already exported, authorized quiescent test copies with predeclared reproduction queries. Compare the team's current scripts/configured tools against FixtureWeaver on the same seeds/acceptance criteria. Record retained rows, bytes, runtime, repair time, unsupported schemas and review effort. Prefer synthetic/already reviewed data: stable masks do not justify sharing production PII.

The economic hypothesis is `avoided repair minutes × measured loaded engineer cost`, minus export, policy setup, execution, review and maintenance. No input to that formula has been measured. Full closure, expensive unindexed collations, exposed protected values and unsupported triggers/WAL can eliminate the benefit. If unsupported schemas/full retention dominate, that is evidence against adoption.

MIT licensing, JSON plans, a Python SDK and registered CLI make evaluation feasible. Sustainable support scope is bounded single-file SQLite fixtures with explicit consumer expectations. Other engines, snapshot capture, privacy guarantees and arbitrary constraint solving are separate work and not promised.
