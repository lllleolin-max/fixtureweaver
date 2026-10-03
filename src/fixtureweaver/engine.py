"""Use SQLite itself for relationship equality and constraint validation."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


class FixtureError(ValueError):
    """Actionable refusal. No output is published on failure."""

    def __init__(self, code: str, message: str, **witness: Any):
        self.code, self.message, self.witness = code, message, witness
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "witness": self.witness}


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def encoded(value: Any) -> str:
    if isinstance(value, bytes):
        return "blob:" + value.hex()
    return type(value).__name__ + ":" + json.dumps(value, ensure_ascii=False, allow_nan=False)


def name_equal(a: str, b: str) -> bool:
    # SQLite identifier case folding is ASCII, not Python's Unicode casefold.
    return a.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")) == b.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


def resolve(name: Any, candidates: Any, kind: str) -> str:
    if isinstance(name, str):
        for candidate in candidates:
            if name_equal(name, candidate):
                return candidate
    raise FixtureError("UNKNOWN_NAME", f"Unknown {kind}; use a declared SQLite identifier", name=name)


@dataclass
class Table:
    name: str
    sql: str
    columns: tuple[str, ...]
    pk: tuple[str, ...]
    locator: tuple[str, ...]
    rowid: bool
    rowid_key: str | None

    @property
    def projection(self) -> str:
        return ",".join(quote(c) for c in self.locator + self.columns)

    def unpack(self, row: tuple) -> tuple[tuple, dict]:
        n = len(self.locator)
        return tuple(row[:n]), dict(zip(self.columns, row[n:]))


@dataclass(frozen=True)
class ForeignKey:
    child: str
    parent: str
    pairs: tuple[tuple[str, str], ...]
    number: int


class Budget:
    def __init__(self, maximum: int):
        self.maximum, self.used = maximum, 0

    def callback(self) -> int:
        self.used += 100
        return int(self.used > self.maximum)

    def attach(self, connection: sqlite3.Connection) -> None:
        connection.set_progress_handler(self.callback, 100)


class DisjointSet:
    def __init__(self, values):
        self.parent = {v: v for v in values}

    def find(self, value):
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while value != root:
            nxt = self.parent[value]
            self.parent[value] = root
            value = nxt
        return root

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[b] = a


def _validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        raise FixtureError("PLAN", "Plan must be an object")
    def scalar_tree(value, depth=0):
        if depth > 64:
            raise FixtureError("PLAN", "Plan nesting exceeds 64 levels")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise FixtureError("PLAN", "Plan object keys must be strings")
                scalar_tree(key, depth + 1)
                scalar_tree(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                scalar_tree(item, depth + 1)
        elif type(value) is int and not -(2 ** 63) <= value < 2 ** 63:
            raise FixtureError("PLAN", "Integer must fit SQLite signed 64-bit storage")
        elif type(value) is float and not math.isfinite(value):
            raise FixtureError("PLAN", "REAL plan values must be finite")
        elif isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeError as error:
                raise FixtureError("PLAN", "Plan strings must be valid UTF-8 scalar values") from error
        elif value is not None and not isinstance(value, (str, int, float, bool, bytes)):
            raise FixtureError("PLAN", "Unsupported plan value type", value_type=type(value).__name__)
    scalar_tree(plan)
    unknown = set(plan) - {"seeds", "masks", "protect", "queries", "salt", "limits"}
    if unknown:
        raise FixtureError("PLAN", "Unknown plan fields", fields=sorted(unknown))
    for key in ("seeds", "masks", "protect", "queries"):
        if not isinstance(plan.get(key, []), list):
            raise FixtureError("PLAN", f"{key} must be an array")
    if not plan.get("seeds"):
        raise FixtureError("PLAN", "At least one nonempty seed selection is required")
    if not isinstance(plan.get("salt", "fixtureweaver-demo"), str) or not plan.get("salt", "fixtureweaver-demo"):
        raise FixtureError("PLAN", "salt must be a nonempty string")
    limits = {"rows": 10000, "cells": 50000, "steps": 10000000, "source_bytes": 128 * 1024 * 1024, "query_rows": 1000}
    supplied = plan.get("limits", {})
    if not isinstance(supplied, dict) or set(supplied) - set(limits):
        raise FixtureError("PLAN", "Unknown or malformed limits")
    limits.update(supplied)
    for key, value in limits.items():
        if type(value) is not int or value <= 0:
            raise FixtureError("PLAN", "Limits must be positive integers", limit=key)
    return limits


def _schema(db: sqlite3.Connection) -> tuple[dict[str, Table], list[ForeignKey], list[str], list[str]]:
    objects = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY name COLLATE BINARY").fetchall()
    tables, indexes, views = {}, [], []
    for kind, name, _, sql in objects:
        if kind == "trigger":
            raise FixtureError("UNSUPPORTED", "Triggers can change fixture semantics; export a trigger-free test schema", object=name)
        if kind == "table":
            details = db.execute(f"PRAGMA table_xinfo({quote(name)})").fetchall()
            flags = db.execute("SELECT wr,type FROM pragma_table_list WHERE schema='main' AND name=?", (name,)).fetchone()
            if not flags or flags[1] != "table" or any(row[6] for row in details):
                raise FixtureError("UNSUPPORTED", "Virtual/shadow tables and generated/hidden columns are unsupported", object=name)
            columns = tuple(row[1] for row in details)
            pk = tuple(row[1] for row in sorted(details, key=lambda x: x[5]) if row[5])
            rowid = not flags[0]
            locator = pk
            if rowid:
                aliases = [n for n in ("_rowid_", "rowid", "oid") if not any(name_equal(n, c) for c in columns)]
                if not aliases:
                    raise FixtureError("UNSUPPORTED", "All SQLite rowid aliases are shadowed", object=name)
                locator = (aliases[0],)
            primary_indexes = [item for item in db.execute(f"PRAGMA index_list({quote(name)})") if item[3] == "pk"]
            # INTEGER PRIMARY KEY aliases rowid unless SQLite built a separate PK index
            # (including the historical INTEGER PRIMARY KEY DESC exception).
            rowid_key = pk[0] if rowid and len(pk) == 1 and not primary_indexes and next(row[2].upper() for row in details if row[1] == pk[0]) == "INTEGER" else None
            tables[name] = Table(name, sql, columns, pk, locator, rowid, rowid_key)
        elif kind == "index" and sql:
            indexes.append(sql)
        elif kind == "view":
            views.append(sql)
    # Prepare a schema clone: SQLite detects custom collations/functions and malformed key models.
    scratch = sqlite3.connect(":memory:")
    try:
        for table in tables.values():
            scratch.execute(table.sql)
        for sql in indexes + views:
            scratch.execute(sql)
    except sqlite3.Error as error:
        raise FixtureError("UNSUPPORTED", "Schema needs unavailable collation/function or cannot be reproduced", detail=str(error)) from error
    finally:
        scratch.close()
    keys = []
    for table in tables.values():
        groups = defaultdict(list)
        for item in db.execute(f"PRAGMA foreign_key_list({quote(table.name)})"):
            groups[item[0]].append(item)
        for number, items in groups.items():
            items.sort(key=lambda x: x[1])
            parent = resolve(items[0][2], tables, "FK parent table")
            target = tables[parent]
            targets = [item[4] for item in items]
            if any(column is None for column in targets):
                if len(items) != len(target.pk):
                    raise FixtureError("KEY_MODEL", "Implicit parent key arity mismatch", table=table.name, fk=number)
                targets = target.pk
            pairs = tuple((resolve(item[3], table.columns, "child column"), resolve(column, target.columns, "parent column")) for item, column in zip(items, targets))
            keys.append(ForeignKey(table.name, parent, pairs, number))
    try:
        issues = db.execute("PRAGMA foreign_key_check").fetchmany(2)
    except sqlite3.Error as error:
        raise FixtureError("KEY_MODEL", "SQLite rejected the declared foreign-key model", detail=str(error)) from error
    if issues:
        raise FixtureError("DANGLING", "Source has foreign-key violations; repair the source before reduction", table=issues[0][0], fk=issues[0][3])
    integrity = db.execute("PRAGMA integrity_check").fetchone()
    if integrity != ("ok",):
        raise FixtureError("INTEGRITY", "Source integrity check failed", detail=integrity)
    return tables, keys, indexes, views


SAFE_FUNCTIONS = {"count", "sum", "total", "avg", "min", "max", "abs", "length", "lower", "upper", "trim", "ltrim", "rtrim", "substr", "substring", "coalesce", "ifnull", "nullif", "typeof", "hex", "round", "printf", "format", "like", "glob", "instr", "replace", "iif"}


def _read_authorizer(action, one, two, database, trigger):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and str(two).lower() in SAFE_FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _select(db, table: Table, selection: dict, limit: int) -> list:
    where = selection.get("where", "1")
    params = selection.get("params", [])
    if not isinstance(where, str) or not where.strip() or not isinstance(params, list):
        raise FixtureError("PLAN", "where must be SQL text and params an array")
    db.set_authorizer(_read_authorizer)
    try:
        rows = db.execute(f"SELECT {table.projection} FROM {quote(table.name)} WHERE ({where}) ORDER BY {','.join(quote(c) for c in table.locator)}", params).fetchmany(limit + 1)
    finally:
        db.set_authorizer(None)
    if len(rows) > limit:
        raise FixtureError("ROW_LIMIT", "Selection exceeds row limit; narrow the seed predicate", limit=limit)
    return rows


def _class_columns(masks: list, tables: dict, keys: list) -> dict[str, set]:
    graph = defaultdict(set)
    for key in keys:
        for child, parent in key.pairs:
            a, b = (key.child, child), (key.parent, parent)
            graph[a].add(b)
            graph[b].add(a)
    classes, occupied = {}, {}
    for mask in masks:
        if not isinstance(mask, dict) or set(mask) != {"name", "columns"} or not isinstance(mask["name"], str) or not mask["name"] or not isinstance(mask["columns"], list) or not mask["columns"]:
            raise FixtureError("PLAN", "Each mask requires a unique name and nonempty columns array")
        name = mask["name"]
        if name in classes:
            raise FixtureError("PLAN", "Duplicate mask class", name=name)
        queue, columns = deque(), set()
        for pair in mask["columns"]:
            if not isinstance(pair, list) or len(pair) != 2:
                raise FixtureError("PLAN", "Mask column must be [table,column]")
            table = resolve(pair[0], tables, "mask table")
            queue.append((table, resolve(pair[1], tables[table].columns, "mask column")))
        while queue:
            column = queue.popleft()
            if column in columns:
                continue
            columns.add(column)
            queue.extend(graph[column] - columns)
        for column in columns:
            if column in occupied:
                raise FixtureError("MASK_CONFLICT", "FK-connected column occurs in two mask classes; merge their declarations", classes=[occupied[column], name], column=list(column))
            occupied[column] = name
        classes[name] = columns
    return classes


def _token(value, token: int, blob: bytes, numeric: bool):
    if isinstance(value, bytes):
        return blob[:16]
    if type(value) is int:
        return token
    if type(value) is float:
        if not math.isfinite(value):
            raise FixtureError("MASK_TYPE", "Nonfinite stored identifiers are unsupported")
        return float(token)
    if isinstance(value, str):
        return str(token) if numeric else "fw_" + blob.hex()[:24]
    raise FixtureError("MASK_TYPE", "Mask supports SQLite INTEGER/REAL/TEXT/BLOB storage classes")


def _masks(db, tables, keys, retained, classes, protect, salt, limits):
    protected = set()
    for rule in protect:
        if not isinstance(rule, dict) or not {"table", "column"} <= set(rule) or set(rule) - {"table", "column", "where", "params"}:
            raise FixtureError("PLAN", "Protect rule requires table,column and optional where,params")
        table = resolve(rule["table"], tables, "protect table")
        column = resolve(rule["column"], tables[table].columns, "protect column")
        for row in _select(db, tables[table], rule, limits["rows"]):
            identity, _ = tables[table].unpack(row)
            if identity in retained[table]:
                protected.add((table, identity, column))
    changes, summaries = {}, []
    for name, columns in sorted(classes.items()):
        cells = {(table, identity, column): values[column] for table, column in sorted(columns) for identity, values in retained[table].items() if values[column] is not None}
        if len(cells) > limits["cells"]:
            raise FixtureError("CELL_LIMIT", "Masked class exceeds cell budget", class_name=name, limit=limits["cells"])
        dsu = DisjointSet(cells)
        # Compare parameters on the *column* side, so its affinity and collation apply.
        for cell, value in cells.items():
            for table, column in sorted(columns):
                t = tables[table]
                result = db.execute(f"SELECT {t.projection} FROM {quote(table)} WHERE {quote(column)} = ?", (value,))
                for row in result:
                    identity, _ = t.unpack(row)
                    other = (table, identity, column)
                    if other in cells:
                        dsu.union(cell, other)
        groups = defaultdict(list)
        for cell in cells:
            groups[dsu.find(cell)].append(cell)
        pinned_groups = 0
        for members in groups.values():
            members.sort(key=lambda c: (c[0], repr(c[1]), c[2]))
            values = [cells[c] for c in members]
            if any(type(value) is float and not math.isfinite(value) for value in values):
                raise FixtureError("MASK_TYPE", "Nonfinite stored identifiers are unsupported", class_name=name)
            storage = {type(v) for v in values}
            if bytes in storage and len(storage) != 1:
                raise FixtureError("MASK_TYPE", "A linked class mixes BLOB and scalar identifiers; separate or normalize the schema", class_name=name)
            fixed = [c for c in members if c in protected]
            pinned_groups += bool(fixed)
            identity = min(encoded(v) for v in values)
            digest = hmac.new(salt.encode("utf-8"), (name + "\0" + identity).encode("utf-8"), hashlib.sha256).digest()
            token = 100000 + int.from_bytes(digest[:6], "big")
            numeric = bool(storage & {int, float})
            for cell in members:
                old = cells[cell]
                if fixed:
                    # Protection pins the entire SQLite equivalence class. Keep each
                    # original storage representation: Python int('1.0') is not SQLite
                    # INTEGER affinity, and int(1.5) would silently truncate a REAL key.
                    new = old
                else:
                    new = _token(old, token, digest, numeric)
                changes[cell] = new
        summaries.append({"name": name, "columns": [list(c) for c in sorted(columns)], "occurrences": len(cells), "equivalence_classes": len(groups), "protected_occurrences": sum(c in protected for c in cells), "pinned_equivalence_classes": pinned_groups})
    return changes, summaries


def _queries(db, queries, maximum):
    output = []
    names = set()
    db.set_authorizer(_read_authorizer)
    try:
        for query in queries:
            if not isinstance(query, dict) or not {"name", "sql", "expect"} <= set(query) or set(query) - {"name", "sql", "params", "expect"}:
                raise FixtureError("PLAN", "Consumer query needs name,sql,expect and optional params")
            name = query["name"]
            if not isinstance(name, str) or name in names:
                raise FixtureError("PLAN", "Consumer query names must be unique strings")
            names.add(name)
            actual = [list(row) for row in db.execute(query["sql"], query.get("params", [])).fetchmany(maximum + 1)]
            if len(actual) > maximum:
                raise FixtureError("QUERY_LIMIT", "Consumer result exceeds query row limit", query=name)
            if actual != query["expect"]:
                raise FixtureError("CONSUMER_QUERY", "Consumer query expectation changed; adjust seeds, protected values or expectations", query=name, expected=query["expect"], actual=actual)
            output.append({"name": name, "passed": True, "result": actual})
    finally:
        db.set_authorizer(None)
    return output


def weave(source: str | Path, destination: str | Path, plan: dict) -> dict:
    """Create one separate SQLite fixture, or raise FixtureError without publishing.

    Sources must be caller-guaranteed quiescent single files, not live WAL databases.
    Constraints and declared queries are verified by the host SQLite library.
    """
    limits = _validate_plan(plan)
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise FixtureError("DESTINATION", "Destination must be a new, separate file")
    if not source.is_file():
        raise FixtureError("SOURCE", "Source must be an existing regular SQLite file")
    if source.stat().st_size > limits["source_bytes"]:
        raise FixtureError("SOURCE_LIMIT", "Source exceeds declared byte bound", limit=limits["source_bytes"])
    if any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise FixtureError("QUIESCENT", "Source has SQLite sidecars; close writers and export a quiescent DELETE-mode copy")
    initial_digest = fingerprint(source)
    budget = Budget(limits["steps"])
    db, output, temporary = None, None, None
    try:
        db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=0.2)
        db.execute("PRAGMA foreign_keys=ON")
        if db.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise FixtureError("SQLITE", "SQLite foreign key enforcement is unavailable")
        if db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            raise FixtureError("QUIESCENT", "WAL-mode sources are outside the single-file contract; export a DELETE-mode copy")
        budget.attach(db)
        db.execute("BEGIN")
        tables, keys, indexes, views = _schema(db)
        counts = {name: db.execute(f"SELECT count(*) FROM {quote(name)}").fetchone()[0] for name in tables}
        classes = _class_columns(plan.get("masks", []), tables, keys)
        retained = {name: {} for name in tables}
        queue = deque()
        total = 0

        def add(table, row):
            nonlocal total
            identity, values = tables[table].unpack(row)
            if identity not in retained[table]:
                total += 1
                if total > limits["rows"]:
                    raise FixtureError("CLOSURE_LIMIT", "Dependency closure exceeds row bound; select fewer seeds or raise the explicit limit", limit=limits["rows"])
                retained[table][identity] = values
                queue.append((table, identity))

        for seed in plan["seeds"]:
            if not isinstance(seed, dict) or "table" not in seed or set(seed) - {"table", "where", "params"}:
                raise FixtureError("PLAN", "Seed requires table and optional where,params")
            table = resolve(seed["table"], tables, "seed table")
            rows = _select(db, tables[table], seed, limits["rows"])
            if not rows:
                raise FixtureError("EMPTY_SEED", "Each seed predicate must select at least one row", table=table)
            for row in rows:
                add(table, row)
        seed_count = total
        edges = 0
        by_child = defaultdict(list)
        for key in keys:
            by_child[key.child].append(key)
        while queue:
            table, identity = queue.popleft()
            values = retained[table][identity]
            for key in by_child[table]:
                child_values = tuple(values[c] for c, _ in key.pairs)
                if any(value is None for value in child_values):
                    continue
                parent = tables[key.parent]
                condition = " AND ".join(f"{quote(p)} = ?" for _, p in key.pairs)
                rows = db.execute(f"SELECT {parent.projection} FROM {quote(parent.name)} WHERE {condition}", child_values).fetchmany(2)
                if len(rows) != 1:
                    raise FixtureError("KEY_MODEL", "Expected one SQLite-resolved parent; repair key declaration", child=table, parent=parent.name, fk=key.number, matches=len(rows))
                add(parent.name, rows[0])
                edges += 1
        changes, mask_summary = _masks(db, tables, keys, retained, classes, plan.get("protect", []), plan.get("salt", "fixtureweaver-demo"), limits)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".fixtureweaver-", suffix=".db", dir=destination.parent)
        os.close(fd)
        temporary = Path(temp_name)
        output = sqlite3.connect(temporary)
        budget.attach(output)
        output.execute("PRAGMA foreign_keys=ON")
        if output.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise FixtureError("SQLITE", "Output SQLite foreign key enforcement is unavailable")
        for table in tables.values():
            output.execute(table.sql)
        for sql in indexes + views:
            output.execute(sql)
        output.execute("BEGIN")
        output.execute("PRAGMA defer_foreign_keys=ON")
        for name, table in tables.items():
            insertion_columns = table.locator + table.columns if table.rowid and table.rowid_key is None else table.columns
            placeholders = ",".join("?" for _ in insertion_columns)
            statement = f"INSERT INTO {quote(name)} ({','.join(quote(c) for c in insertion_columns)}) VALUES ({placeholders})"
            for identity, values in retained[name].items():
                data = [changes.get((name, identity, column), values[column]) for column in table.columns]
                if table.rowid and table.rowid_key is None:
                    data = list(identity) + data
                try:
                    output.execute(statement, data)
                except sqlite3.IntegrityError as error:
                    raise FixtureError("MASK_CONSTRAINT", "Mask/protected values violate a SQLite UNIQUE/CHECK/NOT NULL constraint; change class/protection/schema", table=name, detail=str(error)) from error
        try:
            output.commit()
        except sqlite3.IntegrityError as error:
            raise FixtureError("MASK_CONSTRAINT", "Linked/protected masks cannot satisfy actual foreign keys; remove conflicting protection or normalize identifier domains", detail=str(error)) from error
        violations = output.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise FixtureError("MASK_CONSTRAINT", "Output foreign key check failed", table=violations[0][0], fk=violations[0][3])
        if output.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise FixtureError("INTEGRITY", "Output integrity check failed")
        query_results = _queries(output, plan.get("queries", []), limits["query_rows"])
        output.close()
        output = None
        final_digest = fingerprint(source)
        if final_digest != initial_digest:
            raise FixtureError("SOURCE_CHANGED", "Source bytes changed during build; use a quiescent exported copy")
        report = {"format": "fixtureweaver/1", "source_sha256": initial_digest, "source_unchanged": True, "source_bytes": source.stat().st_size, "fixture_sha256": fingerprint(temporary), "fixture_bytes": temporary.stat().st_size, "source_rows": counts, "retained_rows": {name: len(rows) for name, rows in retained.items()}, "seed_rows": seed_count, "closure_added_rows": total - seed_count, "dependency_edges": edges, "masked_classes": mask_summary, "queries": query_results, "checks": {"foreign_keys": True, "integrity": True}, "sqlite_version": sqlite3.sqlite_version, "vm_steps_upper_counter": budget.used}
        # Hard-link publication is atomic and refuses a concurrently created destination.
        os.link(temporary, destination)
        return report
    except FixtureError:
        raise
    except sqlite3.Error as error:
        code = "WORK_LIMIT" if "interrupted" in str(error) else "SQLITE"
        raise FixtureError(code, "SQLite refused the operation; check the plan/schema or increase an explicit work bound", detail=str(error)) from error
    except (OSError, TypeError, OverflowError) as error:
        raise FixtureError("INPUT_IO", "Could not complete the fixture operation", detail=str(error)) from error
    finally:
        if output is not None:
            output.close()
        if db is not None:
            db.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
