"""Snapshot review: SQL execution and a separate row-based contract oracle."""
import copy
import hashlib
import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext

import duckdb
import sqlglot
from sqlglot import exp

from .importer import identifier
from .sql import Unsupported, validate
from .worker import execute

PASSED = "passed on this snapshot"
ISSUE = "issue found"
LIMITATIONS = [
    "Evidence is conditional on this metric contract and this immutable snapshot, not a proof for future data.",
    "The row oracle currently supports measures and grouping columns from one declared base table; relationship branches may filter or multiply its rows.",
    "Timestamp values must be UTC; other timezone semantics are explicitly unsupported.",
]


def _quote(name):
    return '"' + identifier(name) + '"'


def _literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _check(key, title, status, explanation, sql_location="", contract_clause="", diagnostic_sql="", examples=None, count=None):
    rows = examples or []
    return {"id": key, "title": title, "status": status, "explanation": explanation,
            "sql_location": sql_location, "contract_clause": contract_clause, "diagnostic_sql": diagnostic_sql,
            "count": len(rows) if count is None else count, "examples": rows[:20], "truncated": len(rows) > 20}


def _contract(snapshot, contract):
    required = ["name", "base_table", "grain", "stable_key", "measure", "groups", "relationships", "filters", "time", "units", "null_policy", "decimal_scale", "rounding", "absolute_tolerance", "relative_tolerance"]
    missing = [key for key in required if key not in contract or contract[key] is None or (key in ("grain", "name", "units") and not contract[key])]
    if missing:
        raise ValueError("Define " + ", ".join(missing) + " before reviewing the metric.")
    base = contract["base_table"]
    if base not in snapshot["tables"]:
        raise ValueError("The base table must be present in this snapshot.")
    columns = {c["name"]: c["type"] for c in snapshot["tables"][base]["columns"]}
    if not isinstance(contract["stable_key"], list) or not contract["stable_key"]:
        raise ValueError("Declare at least one stable-key column.")
    if not isinstance(contract["groups"], list) or len(set(contract["groups"])) != len(contract["groups"]):
        raise ValueError("Grouping dimensions must be a list of distinct base columns.")
    for name in contract["stable_key"] + contract["groups"]:
        if name not in columns:
            raise Unsupported(f"{name!r} is not a base-table column; cross-table grains and grouping are not yet supported.")
    seen = set()
    for row in snapshot["tables"][base]["rows"]:
        key = tuple(row[name] for name in contract["stable_key"])
        if None in key or key in seen:
            raise ValueError("The stable key contains NULLs or repeated values. Define a grain and key that identify each base entity.")
        seen.add(key)
    if contract["null_policy"] not in ("exclude", "zero", "preserve"):
        raise ValueError("Null policy must be preserve (SQL aggregate semantics), exclude (remove unknown measures), or zero.")
    if contract["rounding"] not in ("half_even", "half_up") or type(contract["decimal_scale"]) is not int or not 0 <= contract["decimal_scale"] <= 12:
        raise ValueError("Choose half_even or half_up rounding and decimal_scale between 0 and 12.")
    for tolerance in ("absolute_tolerance", "relative_tolerance"):
        value = Decimal(str(contract[tolerance]))
        if not value.is_finite() or value < 0:
            raise ValueError("Tolerances must be finite nonnegative numbers.")
    measure = contract["measure"]
    if not isinstance(measure, dict) or not measure.get("alias"):
        raise ValueError("The measure needs an aggregation and output alias.")
    identifier(measure["alias"])
    if measure["alias"] in contract["groups"]:
        raise ValueError("The measure alias must differ from grouping columns.")
    measures = [measure]
    if measure.get("aggregation") == "ratio":
        if not isinstance(measure.get("numerator"), dict) or not isinstance(measure.get("denominator"), dict):
            raise ValueError("Ratios need explicit numerator and denominator definitions.")
        measures = [measure["numerator"], measure["denominator"]]
    for item in measures:
        if item.get("aggregation") not in ("sum", "count", "count_distinct", "avg"):
            raise Unsupported("Supported measure aggregations are sum, count, count_distinct, avg and explicitly defined ratios.")
        col = item.get("column")
        if col != "*" and col not in columns:
            raise Unsupported("Measure sources must be columns in the declared base table.")
        if col == "*" and item["aggregation"] != "count":
            raise ValueError("Only count may use '*' as its measure source.")
        if item["aggregation"] in ("sum", "avg") and not columns[col].startswith(("INTEGER", "BIGINT", "DOUBLE", "DECIMAL")):
            raise ValueError("SUM and AVG require a numeric measure-source column.")
        if contract["null_policy"] == "zero" and col != "*" and not columns[col].startswith(("INTEGER", "BIGINT", "DOUBLE", "DECIMAL")):
            raise Unsupported("The zero null policy currently supports numeric measure columns only; confirm preserve or exclude for text/date measures.")
    if not isinstance(contract["filters"], list):
        raise ValueError("Filters must be a list, including an empty list for all statuses/cohorts.")
    for clause in contract["filters"]:
        if not isinstance(clause, dict) or clause.get("column") not in columns or clause.get("op") not in ("=", "!=", ">", ">=", "<", "<=", "in", "is_null", "is_not_null"):
            raise ValueError("Each filter needs a base column and supported comparison operator.")
        if clause["op"] == "in" and (not isinstance(clause.get("value"), list) or not clause["value"]):
            raise ValueError("IN filters need a nonempty list of literal values.")
        if clause["op"] not in ("is_null", "is_not_null"):
            if "value" not in clause:
                raise ValueError("Comparison filters require a literal value.")
            values = clause["value"] if clause["op"] == "in" else [clause["value"]]
            for value in values:
                _typed_literal(value, columns[clause["column"]])
    period = contract["time"]
    if not isinstance(period, dict) or "column" not in period or "start" not in period or "end" not in period or not period.get("timezone"):
        raise ValueError("Define time column, half-open start/end bounds and timezone; use null column and bounds for all-time metrics.")
    if period["timezone"] != "UTC":
        raise Unsupported("Only UTC timestamp interpretation is supported. Normalize the imported data and confirm UTC explicitly.")
    if period["column"] is not None:
        if period["column"] not in columns or columns[period["column"]] not in ("DATE", "TIMESTAMP"):
            raise ValueError("The time column must have DATE or TIMESTAMP type.")
        if not isinstance(period["start"], str) or not isinstance(period["end"], str):
            raise ValueError("Both half-open timestamp bounds are required.")
        start, end = datetime.fromisoformat(period["start"]), datetime.fromisoformat(period["end"])
        if start.tzinfo or end.tzinfo or start >= end:
            raise ValueError("Use increasing, timezone-naive UTC interval bounds.")
    elif period["start"] is not None or period["end"] is not None:
        raise ValueError("An all-time metric needs null start and end bounds.")
    if not isinstance(contract["relationships"], list):
        raise ValueError("Relationships must be an explicit list (empty when none).")
    for relationship in contract["relationships"]:
        if not isinstance(relationship, dict) or relationship.get("table") not in snapshot["tables"] or relationship.get("cardinality") not in ("one-to-one", "one-to-many", "many-to-one", "many-to-many"):
            raise ValueError("Each relationship needs an imported table and declared cardinality.")
        remote = {c["name"] for c in snapshot["tables"][relationship["table"]]["columns"]}
        source_table = relationship.get("source_table", base)
        if source_table not in snapshot["tables"]:
            raise ValueError("Each relationship source_table must name an imported table.")
        local = {c["name"] for c in snapshot["tables"][source_table]["columns"]}
        local_keys, remote_keys = relationship.get("local_key"), relationship.get("remote_key")
        if not isinstance(local_keys, list) or not isinstance(remote_keys, list) or not local_keys or len(local_keys) != len(remote_keys) or any(c not in local for c in local_keys) or any(c not in remote for c in remote_keys):
            raise ValueError("Relationship paths need equally sized lists of local and remote key columns.")
    return measures


def _typed_literal(value, kind):
    if value is None:
        return None
    if kind.startswith(("INTEGER", "BIGINT", "DOUBLE", "DECIMAL")):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("Numeric filters require a number or exact numeric string.")
        try:
            number = Decimal(str(value))
        except Exception as error:
            raise ValueError("Numeric filters require a valid numeric literal.") from error
        if not number.is_finite():
            raise ValueError("Numeric filter values must be finite.")
        return number
    if kind in ("DATE", "TIMESTAMP"):
        if not isinstance(value, str):
            raise ValueError("Date filters require ISO date/time strings.")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            raise ValueError("Date filter values must use timezone-naive UTC.")
        return parsed
    if kind == "BOOLEAN" and type(value) is not bool:
        raise ValueError("Boolean filter values must be true or false.")
    if kind == "VARCHAR" and not isinstance(value, str):
        raise ValueError("Text filter values must be strings.")
    return value


def _comparison(value, target, operator, kind):
    if operator == "is_null":
        return value is None
    if operator == "is_not_null":
        return value is not None
    if value is None or target is None:
        return False
    if operator == "in":
        return any(_comparison(value, item, "=", kind) for item in target)
    value, target = _typed_literal(value, kind), _typed_literal(target, kind)
    return {"=": lambda: value == target, "!=": lambda: value != target,
            ">": lambda: value > target, ">=": lambda: value >= target,
            "<": lambda: value < target, "<=": lambda: value <= target}[operator]()


def _population(row, contract, measures, column_types):
    filters = all(_comparison(row[c["column"]], c.get("value"), c["op"], column_types[c["column"]]) for c in contract["filters"])
    period = contract["time"]
    temporal = True
    if period["column"]:
        value = row[period["column"]]
        temporal = value is not None and datetime.fromisoformat(period["start"]) <= datetime.fromisoformat(value) < datetime.fromisoformat(period["end"])
    known = all(m["column"] == "*" or row[m["column"]] is not None for m in measures)
    nulls = known or contract["null_policy"] != "exclude"
    return filters, temporal, nulls, known


def _aggregate(rows, measure, null_policy, column_types):
    column, aggregation = measure["column"], measure["aggregation"]
    values = [1 if column == "*" else row[column] for row in rows]
    if null_policy == "zero":
        values = [0 if value is None else value for value in values]
    values = [value for value in values if value is not None]
    if column != "*":
        values = [_typed_literal(value, column_types[column]) for value in values]
    if aggregation == "count":
        return Decimal(len(values))
    if aggregation == "count_distinct":
        return Decimal(len(set(values)))
    if not values:
        return None
    total = sum((Decimal(str(value)) for value in values), Decimal(0))
    return total / len(values) if aggregation == "avg" else total


def _reference(snapshot, contract):
    measures = _contract(snapshot, contract)
    column_types = {c["name"]: c["type"] for c in snapshot["tables"][contract["base_table"]]["columns"]}
    rows = [row for row in snapshot["tables"][contract["base_table"]]["rows"] if all(_population(row, contract, measures, column_types)[:3])]
    groups = defaultdict(list)
    if not contract["groups"]:
        groups[()] = []
    for row in rows:
        groups[tuple(row[column] for column in contract["groups"])].append(row)
    output = []
    for keys, members in groups.items():
        value = _aggregate(members, measures[0], contract["null_policy"], column_types)
        if contract["measure"]["aggregation"] == "ratio":
            denominator = _aggregate(members, measures[1], contract["null_policy"], column_types)
            value = None if denominator is None or denominator == 0 or value is None else value / denominator
        output.append({**dict(zip(contract["groups"], keys)), contract["measure"]["alias"]: None if value is None else str(value)})
    return {"columns": contract["groups"] + [contract["measure"]["alias"]], "rows": output, "row_count": len(output)}, rows


def reference(snapshot, contract):
    with localcontext() as context:
        context.prec = 60
        return _reference(snapshot, contract)


def _filter_sql(contract, alias=""):
    prefix = f"{_quote(alias)}." if alias else ""
    terms = []
    for clause in contract["filters"]:
        column, operator = prefix + _quote(clause["column"]), clause["op"]
        if operator in ("is_null", "is_not_null"):
            terms.append(column + (" IS NULL" if operator == "is_null" else " IS NOT NULL"))
        elif operator == "in":
            terms.append(f"{column} IN ({', '.join(_literal(value) for value in clause['value'])})")
        else:
            terms.append(f"{column} {operator} {_literal(clause.get('value'))}")
    period = contract["time"]
    if period["column"]:
        column = prefix + _quote(period["column"])
        terms += [f"{column} >= {_literal(period['start'])}", f"{column} < {_literal(period['end'])}"]
    if contract["null_policy"] == "exclude":
        measures = [contract["measure"]] if contract["measure"]["aggregation"] != "ratio" else [contract["measure"]["numerator"], contract["measure"]["denominator"]]
        terms += [prefix + _quote(m["column"]) + " IS NOT NULL" for m in measures if m["column"] != "*"]
    return " AND ".join(terms)


def _repair(contract, query):
    alias = "b"
    def metric(measure):
        column = "*" if measure["column"] == "*" else f"b.{_quote(measure['column'])}"
        if column != "*" and contract["null_policy"] == "zero":
            column = f"COALESCE({column}, 0)"
        aggregation = measure["aggregation"]
        return f"COUNT(DISTINCT {column})" if aggregation == "count_distinct" else f"{aggregation.upper()}({column})"
    measure = contract["measure"]
    expression = metric(measure) if measure["aggregation"] != "ratio" else f"{metric(measure['numerator'])} / NULLIF({metric(measure['denominator'])}, 0)"
    groups = [f"b.{_quote(col)}" for col in contract["groups"]]
    projection = ", ".join(groups + [f"{expression} AS {_quote(measure['alias'])}"])
    sql = f"SELECT {projection}\nFROM {_quote(contract['base_table'])} AS {alias}"
    # The contract defines the population on the base table, so branch presence is not an implicit filter.
    where = _filter_sql(contract, alias)
    if where:
        sql += "\nWHERE " + where
    if groups:
        sql += "\nGROUP BY " + ", ".join(groups) + "\nORDER BY " + ", ".join(groups)
    return {"sql": sql, "explanation": "Calculate the declared base-grain metric directly, with the confirmed population, date interval and null policy. Unused relationship branches are removed; the contract is unchanged."}


def _key_query(contract, keys):
    columns = contract["stable_key"]
    terms = ["(" + " AND ".join(f"{_quote(col)} = {_literal(value)}" for col, value in zip(columns, key)) + ")" for key in keys]
    return f"SELECT * FROM {_quote(contract['base_table'])} WHERE " + (" OR ".join(terms) if terms else "FALSE")


def _display_number(value, scale):
    return str(value) if abs(value) > Decimal(2**53 - 1).scaleb(-scale) else float(value)


def _total(result, alias, aggregation, scale):
    if aggregation in ("avg", "ratio", "count_distinct") and result["row_count"] > 1:
        return None
    values = [Decimal(str(row[alias])) for row in result["rows"] if row.get(alias) is not None]
    return _display_number(sum(values), scale) if values else None


def _result_witness(query, contract, differences):
    keys, metric = contract["groups"], _quote(contract["measure"]["alias"])
    group_columns = ", ".join(_quote(key) for key in keys)
    prefix = group_columns + ", " if keys else ""
    grouping = " GROUP BY " + group_columns if keys else ""
    actual = f"SELECT {prefix}COUNT(*) AS __n, MAX({metric}) AS __value FROM ({query.sql(dialect='duckdb')}) AS result{grouping}"
    expected = f"SELECT *, 1 AS __present FROM ({_repair(contract, query)['sql']}) AS expected_result"
    join = " AND ".join(f"a.{_quote(key)} IS NOT DISTINCT FROM e.{_quote(key)}" for key in keys) or "TRUE"
    columns = ", ".join(f"COALESCE(a.{_quote(key)}, e.{_quote(key)}) AS {_quote(key)}" for key in keys)
    if columns:
        columns += ", "
    predicates = []
    for difference in differences:
        terms = []
        for key, value in difference["keys"].items():
            column = f"COALESCE(a.{_quote(key)}, e.{_quote(key)})"
            terms.append(column + (" IS NULL" if value is None else f" = {_literal(value)}"))
        predicates.append("(" + (" AND ".join(terms) or "TRUE") + ")")
    predicate = " OR ".join(predicates) or "FALSE"
    return (f"SELECT {columns}a.__value AS original, e.{metric} AS reference FROM ({actual}) AS a FULL OUTER JOIN ({expected}) AS e ON {join} "
            f"WHERE {predicate}")


def _denominator_query(query, contract, alias):
    measure = contract["measure"]
    if measure["aggregation"] == "ratio":
        return _ratio_denominator_query(query, contract, alias)
    if measure["aggregation"] != "avg" or contract["null_policy"] != "preserve":
        return None
    projection = next((p for p in query.expressions if p.alias_or_name == measure["alias"]), None)
    if projection is None:
        return None
    denominators = {}
    for expression in projection.walk():
        observed = None
        if isinstance(expression, exp.Div):
            numerator, denominator = expression.this, expression.expression
            while isinstance(numerator, (exp.Cast, exp.Paren)):
                numerator = numerator.this
            while isinstance(denominator, (exp.Cast, exp.Paren, exp.Nullif)):
                denominator = denominator.this
            if isinstance(numerator, exp.Sum) and isinstance(numerator.this, exp.Column) and numerator.this.name == measure["column"] and isinstance(denominator, exp.Count):
                observed = denominator.copy()
        elif isinstance(expression, exp.Avg) and isinstance(expression.this, exp.Coalesce):
            if isinstance(expression.this.this, exp.Column) and expression.this.this.name == measure["column"]:
                observed = exp.Count(this=expression.this.copy())
        if observed is not None:
            denominators[observed.sql()] = observed
    if not denominators:
        return None
    expected = exp.Count(this=exp.column(measure["column"], table=alias))
    witness = query.copy()
    witness.set("expressions", [exp.column(c, table=alias) for c in contract["groups"]] + [
        exp.alias_(observed.copy(), "observed_denominator" + (f"_{index}" if index else "")) for index, observed in enumerate(denominators.values())] + [exp.alias_(expected.copy(), "expected_denominator")])
    comparisons = [exp.NEQ(this=observed, expression=expected.copy()) for observed in denominators.values()]
    predicate = comparisons[0]
    for comparison in comparisons[1:]:
        predicate = exp.Or(this=predicate, expression=comparison)
    witness.set("having", exp.Having(this=predicate))
    witness.set("order", None)
    return witness.sql(dialect="duckdb")


def _ratio_denominator_query(query, contract, alias):
    measure = contract["measure"]
    projection = next((p for p in query.expressions if p.alias_or_name == measure["alias"]), None)
    if projection is None:
        return None

    def aggregation(part):
        column = "*" if part["column"] == "*" else f"{_quote(alias)}.{_quote(part['column'])}"
        if column != "*" and contract["null_policy"] == "zero":
            column = f"COALESCE({column}, 0)"
        sql = f"COUNT(DISTINCT {column})" if part["aggregation"] == "count_distinct" else f"{part['aggregation'].upper()}({column})"
        return sqlglot.parse_one(sql, read="duckdb")

    def normalized(node):
        while isinstance(node, (exp.Cast, exp.Paren)):
            node = node.this
        node = node.copy()
        for identifier_node in node.find_all(exp.Identifier):
            identifier_node.set("quoted", False)
        return node

    numerator = normalized(aggregation(measure["numerator"]))
    expected = exp.Nullif(this=aggregation(measure["denominator"]), expression=exp.Literal.number(0))
    observed = [division.expression.copy() for division in projection.find_all(exp.Div)
                if normalized(division.this) == numerator]
    if not observed:
        return None
    # Zero numerators can conceal a changed denominator in every displayed group.
    witness = query.copy()
    witness.set("expressions", [exp.column(c, table=alias) for c in contract["groups"]] + [
        exp.alias_(node.copy(), f"observed_denominator_{index}") for index, node in enumerate(observed)
    ] + [exp.alias_(expected.copy(), "expected_denominator")])
    comparisons = [exp.NullSafeNEQ(this=exp.Nullif(this=node, expression=exp.Literal.number(0)), expression=expected.copy()) for node in observed]
    predicate = comparisons[0]
    for comparison in comparisons[1:]:
        predicate = exp.Or(this=predicate, expression=comparison)
    witness.set("having", exp.Having(this=predicate))
    witness.set("order", None)
    return witness.sql(dialect="duckdb")


def _compare(actual, expected, contract):
    keys, metric = contract["groups"], contract["measure"]["alias"]
    if len(actual["columns"]) != len(keys) + 1 or set(actual["columns"]) != set(keys + [metric]):
        raise Unsupported("Project each declared grouping column and the metric with its contract alias: " + ", ".join(keys + [metric]))
    actual_groups = defaultdict(list)
    for row in actual["rows"]:
        actual_groups[tuple(row[k] for k in keys)].append(row[metric])
    expected_groups = {tuple(row[k] for k in keys): row[metric] for row in expected["rows"]}
    differences = []
    scale = Decimal(1).scaleb(-contract["decimal_scale"])
    rounding = ROUND_HALF_EVEN if contract["rounding"] == "half_even" else ROUND_HALF_UP
    for key in actual_groups.keys() | expected_groups.keys():
        values = actual_groups.get(key, [])
        wanted = expected_groups.get(key)
        found = values[0] if len(values) == 1 else None
        reason = None
        if key not in expected_groups:
            reason = "unexpected group"
        elif not values:
            reason = "absent group"
        elif len(values) > 1:
            reason = "duplicate group"
        elif (found is None) != (wanted is None):
            reason = "NULL differs from a value"
        elif found is not None:
            left, right = Decimal(str(found)).quantize(scale, rounding), Decimal(str(wanted)).quantize(scale, rounding)
            tolerance = max(Decimal(str(contract["absolute_tolerance"])), abs(right) * Decimal(str(contract["relative_tolerance"])))
            if abs(left - right) > tolerance:
                reason = "value differs beyond declared rounding/tolerance"
        if reason:
            differences.append({"keys": dict(zip(keys, key)), "original": found, "reference": wanted, "reason": reason})
    return differences


def _review(snapshot, contract, sql, cancel_event=None):
    started = time.monotonic()
    base_result = {"status": "failed", "checks": [], "original": None, "reference": None, "difference": None, "proposal": None,
                   "snapshot_id": snapshot["id"], "contract_hash": hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest(),
                   "sql": sql, "contract": copy.deepcopy(contract), "limitations": LIMITATIONS,
                   "versions": {"duckdb": duckdb.__version__, "sqlglot": sqlglot.__version__, "engine": "0.1.0"}}
    try:
        query = validate(sql, snapshot["tables"])
        try:
            measures = _contract(snapshot, contract)
        except (ValueError, TypeError, KeyError) as error:
            if isinstance(error, Unsupported):
                raise
            base_result.update(status="needs definition", checks=[_check("contract", "Metric definition", "needs definition", str(error), contract_clause="Required metric contract fields")])
            return base_result
        source = query.args["from_"].this
        if source.name != contract["base_table"]:
            raise Unsupported("The outer query must start from the contract's base table; use aggregate CTEs for relationship branches.", source.sql())
        alias = source.alias_or_name
        ctes = {cte.alias: cte.this for cte in (query.args.get("with_").expressions if query.args.get("with_") else [])}
        joined_sources = {alias: (source.name, None)}
        for join in query.args.get("joins", []):
            table = join.this.name
            branch = ctes.get(table)
            underlying = branch.args["from_"].this.name if branch is not None else table
            pairs = []
            local_alias = None
            for equality in join.args["on"].find_all(exp.EQ):
                left, right = equality.this, equality.expression
                if left.table == join.this.alias_or_name:
                    left, right = right, left
                if left.table not in joined_sources or right.table != join.this.alias_or_name or (local_alias is not None and local_alias != left.table):
                    raise Unsupported("Each relationship join must connect one earlier table to the new branch through a declared path.", equality.sql())
                local_alias = left.table
                local_column = left.name
                local_table, local_branch = joined_sources[local_alias]
                if local_branch is not None:
                    projected = next((p for p in local_branch.expressions if p.alias_or_name == local_column), None)
                    if isinstance(projected, exp.Alias):
                        projected = projected.this
                    if not isinstance(projected, exp.Column):
                        raise Unsupported("A relationship CTE must project its local key columns without transforming them.", left.sql())
                    local_column = projected.name
                remote_column = right.name
                if branch is not None:
                    projected = next((p for p in branch.expressions if p.alias_or_name == remote_column), None)
                    if isinstance(projected, exp.Alias):
                        projected = projected.this
                    if not isinstance(projected, exp.Column):
                        raise Unsupported("A relationship CTE must project its remote key columns without transforming them.", right.sql())
                    remote_column = projected.name
                pairs.append((local_column, remote_column))
            relationships = [relation for relation in contract["relationships"] if relation["table"] == underlying and relation.get("source_table", source.name) == local_table]
            if not relationships:
                base_result.update(status="needs definition", checks=[_check("relationships", "Declared relationship paths", "needs definition", f"Declare the relationship from {local_table} to {underlying} before reviewing this join.", join.sql(), "relationships")])
                return base_result
            relationships = [r for r in relationships if set(pairs) == set(zip(r["local_key"], r["remote_key"]))]
            if not relationships:
                raise Unsupported("These join keys do not match a declared relationship path. Review the contract or use its declared equijoin keys.", join.sql())
            for relationship in relationships:
                for table_name, columns, should_be_unique in (
                    (local_table, relationship["local_key"], relationship["cardinality"] in ("one-to-one", "one-to-many")),
                    (underlying, relationship["remote_key"], relationship["cardinality"] in ("one-to-one", "many-to-one")),
                ):
                    keys = [tuple(row[c] for c in columns) for row in snapshot["tables"][table_name]["rows"]]
                    nonnull = [key for key in keys if None not in key]
                    if should_be_unique and len(nonnull) != len(set(nonnull)):
                        base_result.update(status="needs definition", checks=[_check("relationships", "Relationship cardinality", "needs definition", f"{table_name} repeats a relationship key declared unique by {relationship['cardinality']}. Confirm the actual cardinality.", join.sql(), json.dumps(relationship))])
                        return base_result
            joined_sources[join.this.alias_or_name] = (underlying, branch)
        lineage = query.copy()
        lineage.set("expressions", [exp.column(column, table=alias) for column in contract["stable_key"]] + [exp.alias_(exp.Count(this=exp.Star()), "__multiplicity")])
        lineage.set("group", exp.Group(expressions=[exp.column(column, table=alias) for column in contract["stable_key"]]))
        lineage.set("order", None)
        denominator_query = _denominator_query(query, contract, alias)
        executed = execute(snapshot, [query.sql(dialect="duckdb"), lineage.sql(dialect="duckdb")] + ([denominator_query] if denominator_query else []), cancel_event)
        original, population = executed[:2]
        base_result["worker_peak_rss_bytes"] = original.get("worker_peak_rss_bytes")
        expected, expected_rows = reference(snapshot, contract)
        base_result.update(original=original, reference=expected)
        differences = _compare(original, expected, contract)
        stable_key = contract["stable_key"]
        column_types = {c["name"]: c["type"] for c in snapshot["tables"][contract["base_table"]]["columns"]}
        key_of = lambda row: tuple(row[col] for col in stable_key)
        actual_counts = {key_of(row): row["__multiplicity"] for row in population["rows"]}
        expected_keys = {key_of(row) for row in expected_rows}
        base_rows = {key_of(row): row for row in snapshot["tables"][contract["base_table"]]["rows"]}
        actual_keys = set(actual_counts)
        missing, unexpected = expected_keys - actual_keys, actual_keys - expected_keys
        duplicate_keys = {key for key, count in actual_counts.items() if count > 1}
        duplicate_rows = []
        measure_column = measures[0]["column"]
        for key in sorted(duplicate_keys, key=repr):
            row = base_rows[key]
            value = row.get(measure_column)
            duplicate_rows.append({**dict(zip(stable_key, key)), "multiplicity": actual_counts[key], "measure": value,
                                   "extra_contribution": None if value is None or measures[0]["aggregation"] != "sum" else str(Decimal(str(value)) * (actual_counts[key] - 1))})
        witness = lineage.copy()
        witness.set("having", exp.Having(this=exp.GT(this=exp.Count(this=exp.Star()), expression=exp.Literal.number(1))))
        checks = [_check("grain", "One contribution per entity", ISSUE if duplicate_keys else PASSED,
                         f"{len(duplicate_keys)} base entities occur more than once after the joins. Repeated totals can inflate the result." if duplicate_keys else "Every selected entity contributes at most one intermediate row.",
                         "\n".join(join.sql() for join in query.args.get("joins", [])) or source.sql(),
                         f"Grain: {contract['grain']}; stable key: {', '.join(stable_key)}", witness.sql(dialect="duckdb"), duplicate_rows)]
        filter_bad, date_bad, null_bad = set(), set(), set()
        for key in missing | unexpected:
            row = base_rows[key]
            filters, temporal, nulls, known = _population(row, contract, measures, column_types)
            if key in unexpected:
                if not filters:
                    filter_bad.add(key)
                if not temporal:
                    date_bad.add(key)
                if not nulls:
                    null_bad.add(key)
            else:
                if not known:
                    null_bad.add(key)
                else:
                    filter_bad.add(key)
                    if contract["time"]["column"] and any(c.name == contract["time"]["column"] for c in (query.args.get("where") or exp.Where()).find_all(exp.Column)):
                        date_bad.add(key)
        # Even identical totals do not establish that the declared population was preserved.
        for check_id, title, affected, clause in (
            ("population", "Included population", filter_bad, json.dumps(contract["filters"])),
            ("dates", "Half-open date interval", date_bad, json.dumps(contract["time"])),
            ("nulls", "Unknown values and denominators", null_bad, contract["null_policy"]),
        ):
            examples = [{**base_rows[key], "reason": "missing from query" if key in missing else "unexpected in query"} for key in sorted(affected, key=repr)]
            explanation = f"{len(affected)} entities disagree with the declared population. Inspect these rows and the query predicates." if affected else "The observed entity population agrees with this clause on the snapshot."
            checks.append(_check(check_id, title, ISSUE if affected else PASSED, explanation,
                                 query.args["where"].sql() if query.args.get("where") else "No WHERE clause", clause, _key_query(contract, sorted(affected, key=repr)), examples))
        metric_alias = contract["measure"]["alias"]
        aggregation = contract["measure"]["aggregation"]
        original["total"], expected["total"] = _total(original, metric_alias, aggregation, contract["decimal_scale"]), _total(expected, metric_alias, aggregation, contract["decimal_scale"])
        original["summary_kind"] = expected["summary_kind"] = "nonadditive groups" if aggregation in ("avg", "ratio", "count_distinct") and max(original["row_count"], expected["row_count"]) > 1 else "total"
        original_total = sum((Decimal(str(row[metric_alias])) for row in original["rows"] if row[metric_alias] is not None), Decimal(0))
        reference_total = sum((Decimal(str(row[metric_alias])) for row in expected["rows"] if row[metric_alias] is not None), Decimal(0))
        exact_difference = original_total - reference_total
        absolute = None if original["total"] is None or expected["total"] is None else _display_number(exact_difference, contract["decimal_scale"])
        checks.append(_check("results", "Independent grouped result", ISSUE if differences else PASSED,
                             f"{len(differences)} groups differ from the independent row calculation." if differences else "Every complete group matches the independent row calculation within the declared rounding and tolerances.",
                             ", ".join(item.sql() for item in query.expressions), json.dumps(contract["measure"]), _result_witness(query, contract, differences), differences))
        # Unknown inputs can affect AVG/COUNT denominators without removing their entity from the FROM population.
        null_rows = [row for row in expected_rows if not _population(row, contract, measures, column_types)[3]]
        if differences and null_rows and not duplicate_keys and not missing and not unexpected:
            checks[3] = _check("nulls", "Unknown values and denominators", ISSUE,
                               "The selected population is intact, but the aggregate differs while unknown measure values are present. Compare COALESCE and COUNT/AVG denominator semantics with the null policy.",
                               ", ".join(item.sql() for item in query.expressions), contract["null_policy"], _key_query(contract, [key_of(row) for row in null_rows]), null_rows)
        if denominator_query and executed[2]["rows"]:
            checks[3] = _check("nulls", "Unknown values and denominators", ISSUE,
                               "The query's denominator differs from the declared measure denominator. This remains an issue when final values coincide, including zero numerators and all-NULL groups.",
                               ", ".join(item.sql() for item in query.expressions), json.dumps(contract["measure"]), denominator_query, executed[2]["rows"])
        status = ISSUE if any(check["status"] == ISSUE for check in checks) else PASSED
        base_result.update(status=status, checks=checks,
                           difference={"absolute": absolute, "percent": None if not reference_total or absolute is None else float(exact_difference / abs(reference_total) * 100),
                                       "groups": differences[:20], "group_count": len(differences), "groups_truncated": len(differences) > 20,
                                       "population": {"expected": len(expected_keys), "observed": len(actual_keys), "missing": len(missing), "unexpected": len(unexpected)}},
                           proposal=_repair(contract, query) if status == ISSUE else None)
        return base_result
    except Unsupported as error:
        base_result.update(status="unsupported", checks=[_check("supported", "Supported analysis", "unsupported", str(error), error.expression)])
        return base_result
    except InterruptedError as error:
        base_result.update(status="interrupted", checks=[_check("execution", "Query execution", "interrupted", str(error))])
        return base_result
    except Exception as error:
        base_result.update(status="failed", checks=[_check("execution", "Query execution", "failed", str(error))])
        return base_result
    finally:
        base_result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)


def review(snapshot, contract, sql, cancel_event=None):
    with localcontext() as context:
        context.prec = 60
        return _review(snapshot, contract, sql, cancel_event)
