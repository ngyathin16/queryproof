"""Fictional commerce rows authored for this demonstration; no customer data."""
import copy

CONTRACT = {
    "name": "October paid revenue", "base_table": "orders", "grain": "one order",
    "stable_key": ["order_id"], "measure": {"column": "revenue", "aggregation": "sum", "alias": "revenue"},
    "groups": ["region"], "relationships": [
        {"table": "items", "local_key": ["order_id"], "remote_key": ["order_id"], "cardinality": "one-to-many"},
        {"table": "touches", "local_key": ["order_id"], "remote_key": ["order_id"], "cardinality": "one-to-many"}],
    "filters": [{"column": "status", "op": "in", "value": ["paid"]}],
    "time": {"column": "ordered_at", "start": "2026-10-01", "end": "2026-11-01", "timezone": "UTC"},
    "units": "USD", "null_policy": "preserve", "decimal_scale": 2, "rounding": "half_even",
    "absolute_tolerance": 0, "relative_tolerance": 0,
}
FILTER = "o.status = 'paid' AND o.ordered_at >= '2026-10-01' AND o.ordered_at < '2026-11-01'"
BAD_SQL = f"""SELECT o.region, SUM(o.revenue) AS revenue
FROM orders AS o
LEFT JOIN items AS i ON o.order_id = i.order_id
LEFT JOIN touches AS t ON o.order_id = t.order_id
WHERE {FILTER}
GROUP BY o.region
ORDER BY o.region"""
GOOD_SQL = f"""WITH item_orders AS (
  SELECT order_id, COUNT(*) AS item_count FROM items GROUP BY order_id
), touch_orders AS (
  SELECT order_id, COUNT(*) AS touch_count FROM touches GROUP BY order_id
)
SELECT o.region, SUM(o.revenue) AS revenue
FROM orders AS o
LEFT JOIN item_orders AS i ON o.order_id = i.order_id
LEFT JOIN touch_orders AS t ON o.order_id = t.order_id
WHERE {FILTER}
GROUP BY o.region
ORDER BY o.region"""


def commerce_bundle():
    return {"manifest": {"name": "Northstar Commerce · October 2026", "tables": [
        {"name": "orders", "file": "orders.csv", "columns": [
            {"name": "order_id", "type": "INTEGER"}, {"name": "region", "type": "VARCHAR"},
            {"name": "status", "type": "VARCHAR"}, {"name": "ordered_at", "type": "TIMESTAMP"},
            {"name": "revenue", "type": "DECIMAL(12,2)"}]},
        {"name": "items", "file": "items.csv", "columns": [
            {"name": "item_id", "type": "INTEGER"}, {"name": "order_id", "type": "INTEGER"}]},
        {"name": "touches", "file": "touches.csv", "columns": [
            {"name": "touch_id", "type": "INTEGER"}, {"name": "order_id", "type": "INTEGER"}]}]},
        "files": {
            "orders.csv": "order_id,region,status,ordered_at,revenue\n1,Hong Kong,paid,2026-10-02,120.00\n2,Hong Kong,paid,2026-10-08,80.00\n3,Singapore,paid,2026-10-12,150.00\n4,Singapore,paid,2026-10-15,50.00\n5,Hong Kong,cancelled,2026-10-18,95.00\n6,Singapore,paid,2026-11-01,200.00\n7,Hong Kong,paid,2026-09-30,60.00\n8,Singapore,paid,2026-10-22,\n",
            "items.csv": "item_id,order_id\n101,1\n102,1\n103,2\n104,3\n105,3\n106,3\n107,4\n108,5\n109,6\n110,7\n",
            "touches.csv": "touch_id,order_id\n201,1\n202,1\n203,2\n204,3\n205,4\n206,4\n207,5\n208,6\n209,7\n"}}


def examples():
    missing = copy.deepcopy(CONTRACT)
    missing["null_policy"] = None
    return [
        {"id": "join-multiplication", "title": "Revenue that looks too good", "description": "Two one-to-many joins repeat order totals. Inspect the rows and repair the grain.", "sql": BAD_SQL, "contract": copy.deepcopy(CONTRACT), "bundle": commerce_bundle()},
        {"id": "correct-analysis", "title": "A review that passes", "description": "Preaggregate each branch to preserve one row per order.", "sql": GOOD_SQL, "contract": copy.deepcopy(CONTRACT), "bundle": commerce_bundle()},
        {"id": "missing-definition", "title": "A definition to settle first", "description": "What should happen to an order with unknown revenue? Confirm the null policy before trusting the result.", "sql": GOOD_SQL, "contract": missing, "bundle": commerce_bundle()},
    ]
