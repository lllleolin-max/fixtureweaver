# Primary-source awareness · checked 2026-10-03

FixtureWeaver is a scoped engineering combination for selected-row SQLite integration fixtures, not a claim of algorithmic invention or competitor-wide superiority.

| Primary source | Established capability credited | Consequence |
|---|---|---|
| [SDV data modalities](https://docs.sdv.dev/sdv/integration/overview/data-modalities) | Relational multi-table data, referential integrity, composite keys and self-references. | Relational generation and composite support are not novel alone. |
| [SDV predefined CAG constraints](https://docs.sdv.dev/sdv/modeling/constraint-augmented-generation-cag/predefined-constraints) | Multi-table rules, carry-over columns, references, foreign-to-foreign links and self-referential hierarchies. | Never infer absent protected/reference/linkage functionality from documentation omission. |
| [SDV CAG bundle](https://docs.sdv.dev/sdv/explore/sdv-bundles/cag) | Cross-table business constraints and auto-detection. | This utility does not replace SDV distribution modeling or its constraint framework. |
| [SQLite foreign keys](https://www.sqlite.org/foreignkeys.html) | Parent affinity/collation, composite NULL exemption, per-connection enforcement and deferred insertion. | SQLite itself resolves and validates relationships. |
| [SQLite data types](https://www.sqlite.org/datatype3.html) | Storage classes, affinity and builtin collations. | Raw Python equality is not general FK equality. |
| [SQLite runtime limits](https://www.sqlite.org/c3ref/c_limit_attached.html) | Length/SQL/attachment limits. | Apply engine limits with row/cell/instruction bounds. |
| [SQLite WAL](https://www.sqlite.org/wal.html) and [defer_foreign_keys](https://www.sqlite.org/pragma.html#pragma_defer_foreign_keys) | Multi-file WAL state and transaction-scoped deferral. | Refuse live/WAL sources; validate separate output with actual deferral. |

The demonstrated distinction combines seed-row reduction, actual SQLite equality domains, shared identifier classes, separate DB materialization and consumer acceptance. It does not claim that an incumbent cannot perform any of these steps. No SDV workload was executed.

`examples/contrast.py` explicitly implements seed-only row sampling with independent deterministic column masks. The closure ablation uses the same engine closure and independent masks. All branches share source, seed/mask declarations and acceptance queries. Equal and full-retention adverse cases remain in the output. This demonstrates a useful mechanism difference on finite disclosed synthetic fixtures, not superiority over SDV/Faker/commercial test-data tooling or an absence of undocumented features.

Adoption, willingness to pay, revenue, anonymity, differential privacy, latency savings and production failure reduction remain unknown. Whether this combination improves an engineer's actual existing script/configured incumbent is a pilot question.
