"""The supported grammar is an allowlist, independent of execution restrictions."""
import re
import sqlglot
from sqlglot import exp


class Unsupported(ValueError):
    def __init__(self, message, expression=""):
        super().__init__(message)
        self.expression = expression


ALLOWED = {
    "Select", "With", "CTE", "Table", "TableAlias", "Identifier", "Column", "From", "Join",
    "Where", "And", "EQ", "NEQ", "GT", "GTE", "LT", "LTE", "In", "Is", "Not",
    "Literal", "Null", "Boolean", "Neg", "Paren", "Alias", "Group", "Order", "Ordered",
    "Sum", "Count", "Avg", "Distinct", "Star", "Add", "Sub", "Mul", "Div", "Coalesce",
    "Nullif", "Cast", "DataType", "DataTypeParam",
}


def _fail(node, message):
    raise Unsupported(message, node.sql(dialect="duckdb"))


def _parts(node):
    if isinstance(node, exp.And):
        return _parts(node.this) + _parts(node.expression)
    if isinstance(node, exp.Paren):
        return _parts(node.this)
    return [node]


def _literal(node):
    return isinstance(node, (exp.Literal, exp.Null, exp.Boolean)) or (isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal) and not node.this.is_string)


def validate(sql, table_names):
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 50_000:
        raise Unsupported("Supply one SELECT of at most 50,000 characters.")
    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except sqlglot.errors.ParseError as error:
        raise Unsupported(f"SQL could not be parsed: {error}") from error
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise Unsupported("Only one SELECT is supported; writes and multiple statements are blocked.")
    query = statements[0]
    for node in query.walk():
        if type(node).__name__ not in ALLOWED:
            _fail(node, f"{type(node).__name__} is outside the supported grammar. Use grouped SUM, COUNT or AVG and literal filters.")
        if isinstance(node, exp.Star) and not isinstance(node.parent, exp.Count):
            _fail(node, "A star is supported only inside COUNT(*). Name projected columns explicitly.")
        if isinstance(node, exp.Distinct) and not isinstance(node.parent, exp.Count):
            _fail(node, "DISTINCT is supported only inside COUNT(DISTINCT column).")
        if isinstance(node, exp.Cast):
            target = node.args["to"].sql()
            if not re.fullmatch(r"(?:INT|BIGINT|SMALLINT|TINYINT|DOUBLE|FLOAT|REAL|DECIMAL(?:\(\d+(?:,\s*\d+)?\))?)", target):
                _fail(node, "Only numeric casts are supported. Use explicit string bounds for timestamp filters.")
    with_clause = query.args.get("with_")
    ctes = list(with_clause.expressions) if with_clause else []
    if len(ctes) > 2 or (with_clause and with_clause.args.get("recursive")):
        _fail(with_clause, "Use at most two nonrecursive aggregate CTEs.")
    cte_names = [cte.alias for cte in ctes]
    if len(set(cte_names)) != len(cte_names) or set(cte_names) & set(table_names):
        raise Unsupported("CTE names must be unique and cannot shadow imported tables.")
    for current in [query] + [cte.this for cte in ctes]:
        if not isinstance(current, exp.Select):
            _fail(current, "A CTE must contain a SELECT.")
        source = current.args.get("from_")
        if not source or not isinstance(source.this, exp.Table):
            _fail(current, "Select from a named imported table.")
        group = current.args.get("group")
        if group and (group.args.get("all") is not None or any(not isinstance(item, exp.Column) for item in group.expressions)):
            _fail(group, "GROUP BY must name the grouping columns explicitly.")
        if current is not query:
            if current.args.get("joins") or current.args.get("with_") or source.this.name not in table_names or not list(current.find_all(exp.AggFunc)):
                _fail(current, "CTEs must aggregate one imported base table and cannot reference other CTEs.")
        joins = current.args.get("joins") or []
        if len(joins) > 2:
            _fail(current, "At most two outer INNER/LEFT equijoins are supported.")
        aliases = [source.this.alias_or_name] + [join.this.alias_or_name for join in joins]
        if len(set(aliases)) != len(aliases):
            _fail(current, "Each table needs a distinct alias.")
        for join in joins:
            if not isinstance(join.this, exp.Table) or join.args.get("side") not in (None, "", "LEFT") or join.args.get("kind") not in (None, "", "INNER") or join.args.get("using") or not join.args.get("on"):
                _fail(join, "Use INNER or LEFT JOIN with explicit qualified column equality.")
            for condition in _parts(join.args["on"]):
                if not isinstance(condition, exp.EQ) or not all(isinstance(c, exp.Column) and c.table for c in (condition.this, condition.expression)):
                    _fail(condition, "Join conditions must compare qualified columns, joined with AND.")
                if condition.this.table == condition.expression.table:
                    _fail(condition, "Join keys must connect two different table aliases.")
        where = current.args.get("where")
        if where:
            for condition in _parts(where.this):
                test = condition.this if isinstance(condition, exp.Not) else condition
                if isinstance(test, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
                    valid = not isinstance(condition, exp.Not) and isinstance(test.this, exp.Column) and _literal(test.expression)
                elif isinstance(test, exp.In):
                    valid = not isinstance(condition, exp.Not) and isinstance(test.this, exp.Column) and bool(test.expressions) and all(_literal(item) for item in test.expressions)
                elif isinstance(test, exp.Is):
                    valid = isinstance(test.this, exp.Column) and isinstance(test.expression, exp.Null)
                else:
                    valid = False
                if not valid:
                    _fail(condition, "Filters must be AND-conjoined column/literal comparisons, literal IN lists, or IS [NOT] NULL.")
    allowed_tables = set(table_names) | set(cte_names)
    for table in query.find_all(exp.Table):
        if table.name not in allowed_tables or table.args.get("db") or table.args.get("catalog") or not isinstance(table.this, exp.Identifier):
            _fail(table, "Only tables in the imported snapshot are available; files, functions and external schemas are blocked.")
    return query
