# FixtureWeaver

Reduced SQLite fixtures that still join.

An integration-test engineer selects rows that reproduce a checkout, billing or account bug. FixtureWeaver follows their actual SQLite foreign keys, applies one deterministic mapping to each declared identifier class, creates a separate database, and checks its real constraints and declared consumer queries. It reports the extra rows dependencies require. **Stable pseudonyms retain linkage; no anonymity or privacy guarantee is provided.**

中文：把复现问题所需的少量 SQLite 行补齐外键依赖，统一替换关联标识，生成仍能通过声明查询的独立测试库。适合静止数据库副本上的集成测试夹具；需要匿名化证明、在线快照或通用数据合成时不适用。

## Install and run

With Git installed, start from a new checkout / 首次使用先克隆并进入目录：

```console
git clone https://github.com/lllleolin-max/fixtureweaver.git
cd fixtureweaver
```

Python **3.11+**, SQLite **3.37+**, standard-library runtime. On Windows, use `py -3` in place of `python` if necessary. Run commands from the checkout in the intended Python environment. For an isolated install, run `python -m venv .venv`, then `.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` in Bash. Check your Python's SQLite engine with `python -c "import sqlite3; print(sqlite3.sqlite_version)"`.

```sh
python -m pip install .
python examples/demo.py --out demo-output
```

The demo exercises the installed SDK **and actual registered console executable**, located through the same interpreter's `sysconfig.get_path('scripts')`. Its synthetic checkout retains **5 of 16 rows**, adds 3 dependency rows, passes query `[[120,3,2]]`, preserves source bytes, and produces the same SDK/CLI fixture hash. The tiny database occupies **24,576 bytes both before and after**: disk savings and runtime savings are not established. [Full measured receipt](docs/evidence/release/d6e794aca2d3.json).

Inspect `demo-output/plan.json`, the source `checkout.db`, and the generated `sdk-fixture.db`/`cli-fixture.db`. The directory must be new for a repeated demo; choose another `--out`. To run the CLI yourself with the generated plan:

```console
fixtureweaver demo-output/checkout.db demo-output/another-fixture.db --plan demo-output/plan.json
```

If the command is not on PATH, use `python -m fixtureweaver.cli` with the same arguments. `pip install .` builds and installs a normal wheel.

## SDK and plan

For your own application, make a quiescent supported SQLite copy, select bug-reproducing seed rows, declare linked identifier masks and exact consumer expectations, then call `weave` or the CLI. Point your integration test at the new destination database and preserve the JSON report with its plan. The following SDK snippet illustrates a schema with `orders.account → account.id`; it requires your matching source database. Use the demo above for a self-contained runnable example.

```python
from fixtureweaver import FixtureError, weave

plan = {
    "seeds": [{"table": "orders", "where": "id = ?", "params": [101]}],
    "masks": [{"name": "account", "columns": [["account", "id"]]}],
    "queries": [{"name": "join", "sql":
        "SELECT count(*) FROM orders JOIN account ON account.id=orders.account",
        "expect": [[1]]}],
}
try:
    report = weave("quiescent-copy.db", "fixture.db", plan)
except FixtureError as error:
    print(error.as_dict())  # code/message/witness; no failed output published
```

This snippet illustrates a single-column relationship. The runnable checkout uses tenant/account **composite keys**, NOCASE and TEXT `"01"` referencing INTEGER `1`. SQLite resolves these relationships; Python tuple equality does not decide FK matches.

| Field | Meaning |
|---|---|
| `seeds` | Nonempty `{table,where?,params?}` selections; each selects at least one row. Duplicate rows are retained once. Default predicate is `1`. |
| `masks` | `{name,columns:[[table,column],...]}`. FK-connected component columns expand automatically, including composite keys. Declare unrelated columns separately; equal values alone do not establish a linkage. |
| `protect` | Optional `{table,column,where?,params?}` rules. A protected occurrence **pins its entire equivalence class** in each occurrence's original storage representation. These linked values remain visible. |
| `queries` | `{name,sql,params?,expect:[[...],...]}`; exact ordered finite scalar results. Use `ORDER BY` when order matters and `hex()` for BLOB output. |
| `salt` | Nonempty UTF-8 string; default `fixtureweaver-demo`. Reproducibility setting, not an anonymity credential. |
| `limits` | Positive integer bounds: `rows=10000`, total masked `cells=50000`, `steps=10000000`, `source_bytes=134217728`, `query_rows=1000`, `value_bytes=1048576`. |

Closure only adds **ancestors required by FKs**. Explicitly seed children, unrelated join partners and business dependencies; declare the consumer queries you need. Literal-ID queries may require protection or changed expectations. Protection weakens masking.

CLI success: JSON stdout, exit 0. Build/plan refusal: JSON stderr, exit 2. Usage errors follow `argparse`. Plans are UTF-8 JSON, at most 1 MiB, without duplicate object keys/nonfinite/out-of-range numbers; INTEGER values fit signed 64 bits.

## Executable distinction

`python examples/contrast.py` holds source, seeds, mask declarations and consumer queries constant. The baseline is explicitly implemented seed-only sampling with independent column replacements; an ablation adds closure while still masking independently. **SDV was not executed and competitor feature absence is not claimed.**

| Synthetic case | Sampling + independent | Closure + independent | Closure + shared mapping |
|---|---|---|---|
| Checkout, 16 source rows | 2 retained; 2 FK violations; query fails | 5 retained; 4 FK violations; query fails | 5 retained; 0 violations; query passes |
| Independent ledger, 2 rows | 1 retained; query passes | 1 retained; query passes | 1 retained; query passes |
| Adverse 20-row chain | 1 retained; 1 FK violation | 20 retained; 19 FK violations | 20 retained; valid, **no reduction** |

A ten-row cap refuses the adverse chain with `CLOSURE_LIMIT`. SQLite UNIQUE/CHECK/NOT NULL constraints may reject a chosen mapping. Errors identify the table/constraint and remediation; a different salt can resolve a candidate-token collision. This is not a complete constraint solver or a proof that no feasible mask exists.

[SDV data modalities](https://docs.sdv.dev/sdv/integration/overview/data-modalities) already describes relational data and composite keys. Its [CAG constraints](https://docs.sdv.dev/sdv/modeling/constraint-augmented-generation-cag/predefined-constraints) include multi-table rules and self-referential hierarchies. The demonstrated combination here is **selected-row reduction + SQLite equality domains + shared masks + real database materialization + consumer acceptance**. [Primary sources and comparison boundary](docs/COMPETITORS.md), checked 2026-10-03. Documentation omissions never prove absent capabilities.

## Supported scope and limits

Supports ordinary rowid/WITHOUT ROWID tables, composite/implicit parent keys, actual UNIQUE/partial/expression indexes with builtins, CHECK/NOT NULL/STRICT tables, SQL views, cycles, self-links and deferred insertion when the host engine reproduces the schema. Builtin BINARY/NOCASE/RTRIM semantics apply. NULL is untouched; any NULL composite child component exempts parent lookup. Implicit rowids survive reduction; masking an INTEGER PRIMARY KEY changes its aliased rowid with the key.

Require a **caller-guaranteed quiescent, single-file DELETE-mode copy**. Refuse WAL, sidecars, triggers, virtual/shadow tables, generated/hidden columns and custom collations/functions. Validate the entire source key model/integrity, so even unselected dangling rows block reduction. Open source read-only, hash before/after under a read transaction, and refuse detected byte changes. This is not a concurrent snapshot service; export a consistent offline copy separately.

Destination must be new. Atomic publication uses a hard link from a validated sibling temporary file; the filesystem must support hard links. Failures clean temporary files. Hashes are byte receipts, not privacy certificates. Database byte repeatability is tested on the same source/plan/runtime; different SQLite versions may lay out pages differently. Mapping stability is not guaranteed across changed selections/comparator domains.

Autoincrement sequences are rebuilt by retained inserts; SQLite statistics, application/user-version pragmas and storage settings are not copied. Only declared queries are certified. Read authorizers/bounds reduce accidental misuse; they are not a hostile-input native-engine sandbox. Expensive unindexed equality domains and full closure can eliminate reduction benefits.

## Verification and pilot

Optional checks: `python examples/contrast.py` reproduces the synthetic comparisons; `python -m unittest discover -s tests -v` runs the suite.

[ITERATIONS.md](docs/ITERATIONS.md) records **six** real post-initial correction cycles, each with direct-parent SHAs, an unchanged fail→pass archive-wheel probe and actual logs. Replay: `python tools/verify_history.py`; provenance-only check: add `--records-only`. Fresh full normal archive-wheel check: `python tools/verify_release.py HEAD --out .artifacts/final`.

The suite includes an independent recursive SQLite CTE oracle over 32 small cyclic graphs and adversarial key/mask/constraint/source/budget/console cases. [Architecture](docs/ARCHITECTURE.md), [security](SECURITY.md), [contributing](CONTRIBUTING.md) and [pilot rationale](docs/PILOT.md) describe boundaries. CI covers Ubuntu/Windows × Python 3.11/3.14; checked-in YAML alone does not prove remote success. No customers, revenue or measured production savings are claimed. MIT licensed.

## 中文：做什么、怎么用、为什么

**做什么：** 从少量种子行补齐真实 SQLite 外键依赖，关联标识统一确定性映射，生成独立测试库，并实际检查约束、完整性和业务查询。支持复合键、NULL、循环关系及 NOCASE/类型亲和性等边界。

**怎么用：** 安装后运行 `python examples/demo.py --out demo-output`，再运行 `fixtureweaver demo-output/checkout.db demo-output/new.db --plan demo-output/plan.json`。JSON 声明种子、掩码类、保护规则、查询预期和上限；成功返回报告，失败返回可操作错误，不发布失败结果。保护一个标识会固定整个等价类，关联值仍然可见。

**为什么：** 抽样可能留下悬空外键，逐列替换可能破坏联表，测试因此在无关的数据错误处失败。演示保留 16 行中的 5 行，结账结果保持 `[[120,3,2]]`；同时保留普通账本对照成功、20 行链无法缩减等反例。小库字节数没有减少，不声称成本收益。潜在使用者是维护 SQLite 集成测试的工程团队，采用/付费意愿未知。详见[中文说明](docs/PROJECT_BRIEF_ZH.md)。稳定掩码不等于匿名化或隐私证明。
