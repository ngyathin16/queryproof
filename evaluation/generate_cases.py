"""Specify and freeze synthetic cases without importing the detector or SQL engine."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

ROOT = Path(__file__).parent


def bundle(tables, name):
    manifest = {"name": name, "tables": []}
    files = {}
    for table, (columns, rows) in tables.items():
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=[c["name"] for c in columns], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        filename = table + ".csv"
        manifest["tables"].append({"name": table, "file": filename, "columns": columns})
        files[filename] = output.getvalue()
    return {"manifest": manifest, "files": files}


def oracle(rows, contract):
    """Independent row calculation; no SQL, detector, or suggested repair is called."""
    selected = []
    for row in rows:
        if any((f["op"] == "in" and row[f["column"]] not in f["value"]) or (f["op"] == "=" and row[f["column"]] != f["value"]) for f in contract["filters"]):
            continue
        time = contract["time"]
        if time["column"] and (row[time["column"]] is None or not time["start"] <= row[time["column"]] < time["end"]):
            continue
        if contract["null_policy"] == "exclude" and row[contract["measure"]["column"]] is None:
            continue
        selected.append(row)
    groups = {}
    for row in selected:
        key = tuple(row[name] for name in contract["groups"])
        groups.setdefault(key, []).append(row)
    if not contract["groups"] and not groups:
        groups[()] = []
    results = []
    for key, members in groups.items():
        values = [Decimal(str(row[contract["measure"]["column"]])) for row in members if row[contract["measure"]["column"]] is not None]
        aggregation = contract["measure"]["aggregation"]
        if contract["null_policy"] == "zero":
            values += [Decimal(0)] * (len(members) - len(values))
        if aggregation == "count":
            value = Decimal(len(values))
        elif aggregation == "count_distinct":
            value = Decimal(len(set(values)))
        elif not values:
            value = None
        elif aggregation == "avg":
            value = sum(values) / len(values)
        else:
            value = sum(values)
        if value is not None:
            value = str(value.quantize(Decimal(10) ** -contract["decimal_scale"], rounding=ROUND_HALF_EVEN))
        results.append({**dict(zip(contract["groups"], key)), contract["measure"]["alias"]: value})
    return {"groups": results, "population": [list(row[k] for k in contract["stable_key"]) for row in selected]}


def fixture(split):
    # Development uses compound event identity and AVG; evaluation uses order identity and SUM.
    # Relationship topology and projection shapes therefore differ across the partition.
    dev = split == "development"
    columns = [{"name": name, "type": kind} for name, kind in [("order_id", "INTEGER"), ("tenant_id", "INTEGER"), ("region", "VARCHAR"), ("segment", "VARCHAR"), ("revenue", "DECIMAL(18,2)"), ("status", "VARCHAR"), ("ordered_at", "TIMESTAMP")]]
    raw = [
        (1, 1, "East", "retail", "100.00", "paid", "2026-10-01 00:00:00"),
        (2, 1, "East", "business", "50.00", "paid", "2026-10-15 12:00:00"),
        (3, 2, "West", "retail", "40.00", "paid", "2026-10-31 23:59:59"),
        (4, 2, "West", "business", "900.00", "pending", "2026-10-10 00:00:00"),
        (5, 1, "East", "retail", "800.00", "paid", "2026-11-01 00:00:00"),
        (6, 2, None, "business", None, "paid", "2026-10-20 00:00:00"),
        (7, 1, "West", "retail", "700.00", "paid", "2026-09-30 23:59:59"),
        (8, 2, "East", "retail", "600.00", "paid", None),
        (9, 1, None, "retail", "20.00", "paid", "2026-10-20 00:00:00"),
    ]
    rows = [dict(zip([c["name"] for c in columns], values)) for values in raw]
    child_columns = [{"name": "order_id", "type": "INTEGER"}, {"name": "tenant_id", "type": "INTEGER"}, {"name": "item_id", "type": "INTEGER"}]
    children = [{"order_id": row["order_id"], "tenant_id": row["tenant_id"], "item_id": j} for row in rows for j in range(1, (3 if row["order_id"] in {1, 3} else 2))]
    touches = [{"order_id": row["order_id"], "tenant_id": row["tenant_id"], "item_id": j} for row in rows for j in range(1, (4 if row["order_id"] == 1 else 2))]
    keys = ["tenant_id", "order_id"] if dev else ["order_id"]
    contract = {"name": "Average event value" if dev else "Paid order revenue", "base_table": "orders", "grain": "one event per tenant" if dev else "one order", "stable_key": keys, "measure": {"column": "revenue", "aggregation": "avg" if dev else "sum", "alias": "revenue"}, "groups": ["region", "segment"] if dev else ["region"], "relationships": [{"table": "items", "local_key": keys, "remote_key": keys, "cardinality": "one-to-many"}, {"table": "touches", "local_key": keys, "remote_key": keys, "cardinality": "one-to-many"}], "filters": [{"column": "status", "op": "in", "value": ["paid"]}], "time": {"column": "ordered_at", "start": "2026-10-01", "end": "2026-11-01", "timezone": "UTC"}, "units": "USD", "null_policy": "preserve", "decimal_scale": 2, "rounding": "half_even", "absolute_tolerance": 0, "relative_tolerance": 0}
    tables = {"orders": (columns, rows), "items": (child_columns, children), "touches": (child_columns, touches)}
    return tables, contract


def query(contract, *, joins="", population=None, dates=None, extra="", measure=None, order=False):
    groups = ["o." + name for name in contract["groups"]]
    measure = measure or contract["measure"]["aggregation"].upper() + "(o." + contract["measure"]["column"] + ")"
    filters = [population if population is not None else "o.status IN ('paid')", dates if dates is not None else "o.ordered_at >= '2026-10-01' AND o.ordered_at < '2026-11-01'"]
    if extra:
        filters.append(extra)
    if contract["null_policy"] == "exclude":
        filters.append("o.revenue IS NOT NULL")
    text = "SELECT " + ", ".join(groups + [measure + " AS " + contract["measure"]["alias"]]) + " FROM orders o " + joins + " WHERE " + " AND ".join(f for f in filters if f)
    if groups:
        text += " GROUP BY " + ", ".join(groups)
        if order:
            text += " ORDER BY " + ", ".join(groups) + " DESC"
    return text


def build(split):
    cases = []
    tables, base = fixture(split)

    def add(family, label, contract, sql, expected_status, data=None, repair=None, note=""):
        data = copy.deepcopy(data or tables)
        intended = oracle(data["orders"][1], contract) if expected_status not in {"needs definition", "unsupported"} else None
        cases.append({"id": f"{split}-{family}-{len([c for c in cases if c['family'] == family])+1:02d}", "family": family, "description": label, "structural_pattern": note or label, "bundle": bundle(data, label), "contract": contract, "sql": sql, "expected_status": expected_status, "expected": intended, "repairable": expected_status == "issue found", "known_solution": repair if repair is not None else query(contract) if intended else None})

    key = " AND ".join(f"o.{k} = i.{k}" for k in base["stable_key"])
    touch_key = " AND ".join(f"o.{k} = t.{k}" for k in base["stable_key"])
    joins = [f"LEFT JOIN items i ON {key}", f"INNER JOIN items i ON {key}", f"LEFT JOIN items i ON {key} LEFT JOIN touches t ON {touch_key}", f"INNER JOIN items i ON {key} LEFT JOIN touches t ON {touch_key}", f"LEFT JOIN items i ON {key} INNER JOIN touches t ON {touch_key}", f"INNER JOIN items i ON {key} INNER JOIN touches t ON {touch_key}"]
    for index, join in enumerate(joins):
        contract = copy.deepcopy(base)
        if index % 3 == 1:
            contract["groups"] = []
        if index == 5:
            contract["measure"]["aggregation"] = "count"
        add("join", f"Fanout through relationship shape {index+1}", contract, query(contract, joins=join), "issue found")
    populations = ["", "o.status IN ('paid', 'pending')", "o.status = 'pending'", "o.status IN ('paid') AND o.region = 'East'", "o.status != 'paid'", "o.status IN ('paid') AND o.tenant_id = 1"]
    for index, predicate in enumerate(populations):
        contract = copy.deepcopy(base)
        if index % 2:
            contract["groups"] = []
        add("population", f"Population predicate {index+1}", contract, query(contract, population=predicate), "issue found")
    bounds = ["", "o.ordered_at > '2026-10-01' AND o.ordered_at < '2026-11-01'", "o.ordered_at >= '2026-10-01' AND o.ordered_at <= '2026-11-01'", "o.ordered_at >= '2026-10-02' AND o.ordered_at < '2026-11-01'", "o.ordered_at >= '2026-10-01'", "o.ordered_at < '2026-11-01'"]
    for index, predicate in enumerate(bounds):
        contract = copy.deepcopy(base)
        if index % 2:
            contract["groups"] = []
        add("date", f"Date interval error {index+1}", contract, query(contract, dates=predicate), "issue found")
    for index in range(6):
        contract = copy.deepcopy(base)
        if index == 0:
            sql = query(contract, extra="o.revenue IS NOT NULL")
        elif index == 1:
            sql = query(contract, extra="o.region IS NOT NULL")
        elif index == 2:
            contract["null_policy"] = "zero"
            contract["measure"]["aggregation"] = "avg"
            sql = query(contract)
        elif index == 3:
            contract["measure"]["aggregation"] = "count"
            sql = query(contract, measure="COUNT(*)")
        elif index == 4:
            contract["measure"]["aggregation"] = "avg"
            sql = query(contract, measure="SUM(o.revenue) / COUNT(*)")
        else:
            contract["groups"] = []
            sql = query(contract, extra="o.region IS NOT NULL")
        repair = query(contract, measure="AVG(COALESCE(o.revenue, 0))") if index == 2 else query(contract)
        add("null", f"Null population or denominator error {index+1}", contract, sql, "issue found", repair=repair)
    for index in range(12):
        contract = copy.deepcopy(base)
        kwargs = {}
        if index == 1:
            contract["groups"] = []
        elif index == 2:
            contract["groups"] = ["region", "segment"]
        elif index == 3:
            kwargs["order"] = True
        elif index == 4:
            contract["measure"]["aggregation"] = "avg"
        elif index == 5:
            contract["measure"]["aggregation"] = "count"
        elif index == 6:
            contract["measure"]["aggregation"] = "count_distinct"
            kwargs["measure"] = "COUNT(DISTINCT o.revenue)"
        elif index == 7:
            contract["null_policy"] = "zero"
            kwargs["measure"] = "SUM(COALESCE(o.revenue, 0))" if split == "evaluation" else "AVG(COALESCE(o.revenue, 0))"
        elif index == 8:
            contract["null_policy"] = "exclude"
        elif index == 9:
            kwargs["population"] = "o.status = 'paid'"
        elif index == 10:
            kwargs["measure"] = ("SUM" if split == "evaluation" else "AVG") + "(CAST(o.revenue AS DECIMAL(18,2)))"
        elif index == 11:
            contract["absolute_tolerance"] = 0.01
            kwargs["measure"] = ("SUM" if split == "evaluation" else "AVG") + "(o.revenue) + 0.001"
        sql = query(contract, **kwargs)
        add("valid", f"Valid semantic variation {index+1}", contract, sql, "passed on this snapshot", repair=sql)
    for field in ["base_table", "grain", "stable_key", "measure", "groups", "relationships", "filters", "time", "units", "null_policy", "decimal_scale", "rounding"]:
        contract = copy.deepcopy(base)
        del contract[field]
        add("definition", "Missing " + field, contract, query(base), "needs definition")
    invalid = ["SELECT * FROM orders", "SELECT DISTINCT o.region FROM orders o", "SELECT SUM(o.revenue) FROM orders o LIMIT 1", "SELECT SUM(o.revenue) OVER () FROM orders o", "SELECT o.region, SUM(o.revenue) FROM orders o GROUP BY o.region HAVING SUM(o.revenue)>0", "SELECT * FROM orders UNION SELECT * FROM orders", "SELECT * FROM (SELECT * FROM orders)", "DELETE FROM orders", "COPY orders TO 'leak.csv'", "SELECT * FROM read_csv('secret.csv')", "SELECT SUM(o.revenue) FROM orders o WHERE o.status='paid' OR o.status='pending'", "SELECT SUM(o.revenue) FROM orders o; SELECT 1"]
    for index, sql in enumerate(invalid):
        add("unsupported", f"Unsupported grammar or unsafe input {index+1}", copy.deepcopy(base), sql, "unsupported")
    assert len(cases) == 60
    return cases


def main():
    destination = ROOT / "cases.json"
    if destination.exists():
        raise SystemExit("Frozen cases already exist. Create a new version instead of overwriting evidence.")
    cases = {"version": 1, "provenance": "Agent-specified fictional data; no human review or customer observations.", "development": build("development"), "evaluation": build("evaluation")}
    encoded = (json.dumps(cases, indent=2, ensure_ascii=False) + "\n").encode()
    destination.write_bytes(encoded)
    manifest = {"version": 1, "sha256": hashlib.sha256(encoded).hexdigest(), "counts": {"development": 60, "evaluation": 60}, "per_split": {"join": 6, "population": 6, "date": 6, "null": 6, "valid": 12, "definition": 12, "unsupported": 12}, "oracle": "Pure Python row filtering and Decimal aggregation in generate_cases.py; no detector or DuckDB calls.", "split": "Development: compound tenant/event key, two grouping dimensions, AVG. Evaluation: order key, single grouping dimension, SUM. Shared edge-case concepts disclosed; not externally held out.", "frozen_before_execution": True, "unseen_claim": False}
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
