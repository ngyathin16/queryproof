import copy
import threading
import unittest
from unittest.mock import patch

from queryproof.engine import review
from queryproof.fixtures import CONTRACT, BAD_SQL, GOOD_SQL, commerce_bundle, examples
from queryproof.importer import import_bundle
from queryproof.sql import Unsupported, validate
from queryproof.worker import execute


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = import_bundle(commerce_bundle())

    def test_join_evidence_and_executed_repair(self):
        result = review(self.snapshot, CONTRACT, BAD_SQL)
        self.assertEqual(result["status"], "issue found", result)
        self.assertEqual(result["original"]["total"], 1110)
        self.assertEqual(result["reference"]["total"], 400)
        self.assertEqual(result["checks"][0]["count"], 3)
        for check in result["checks"]:
            observed = execute(self.snapshot, [check["diagnostic_sql"]])[0]
            self.assertEqual(observed["row_count"], check["count"], check)
        fixed = review(self.snapshot, CONTRACT, result["proposal"]["sql"])
        self.assertEqual(fixed["status"], "passed on this snapshot", fixed)
        self.assertEqual(fixed["difference"]["population"], {"expected": 5, "observed": 5, "missing": 0, "unexpected": 0})

    def test_preaggregated_branches_pass(self):
        result = review(self.snapshot, CONTRACT, GOOD_SQL)
        self.assertEqual(result["status"], "passed on this snapshot", result)
        for check in result["checks"]:
            self.assertEqual(execute(self.snapshot, [check["diagnostic_sql"]])[0]["row_count"], check["count"])

    def test_missing_definition_cannot_pass(self):
        for key in ("grain", "null_policy", "time", "units", "measure"):
            contract = copy.deepcopy(CONTRACT)
            del contract[key]
            with self.subTest(key=key):
                self.assertEqual(review(self.snapshot, contract, GOOD_SQL)["status"], "needs definition")

    def test_unsupported_sql(self):
        for sql in ["DROP TABLE orders", "SELECT 1; SELECT 2", "SELECT * FROM read_csv('/etc/passwd')",
                    "ATTACH 'secret.db'", "PRAGMA version", "COPY orders TO 'x.csv'", "SELECT SUM(revenue) FROM orders LIMIT 1",
                    "SELECT SUM(revenue) OVER () FROM orders", "SELECT DISTINCT region FROM orders",
                    "SELECT SUM(revenue) FROM orders HAVING SUM(revenue)>0", "SELECT SUM(revenue) FROM orders UNION SELECT 1",
                    "SELECT SUM(revenue) FROM orders WHERE status='paid' OR status='cancelled'",
                    "SELECT SUM(revenue) FROM orders GROUP BY ALL", "SELECT SUM(revenue) FROM orders RIGHT JOIN items ON orders.order_id=items.order_id",
                    "SELECT SUM(revenue) FROM orders WHERE order_id IN (SELECT order_id FROM items)"]:
            with self.subTest(sql=sql):
                self.assertEqual(review(self.snapshot, CONTRACT, sql)["status"], "unsupported")

    def test_worker_blocks_external_access_even_without_parser(self):
        for sql in ["SELECT * FROM read_csv('C:/Windows/win.ini')", "COPY orders TO 'blocked.csv'", "INSTALL httpfs", "LOAD httpfs", "ATTACH 'other.duckdb'"]:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                execute(self.snapshot, [sql])

    def test_cancel_timeout_recovery(self):
        cancelled = threading.Event()
        cancelled.set()
        self.assertEqual(review(self.snapshot, CONTRACT, GOOD_SQL, cancelled)["status"], "interrupted")
        with self.assertRaises(TimeoutError):
            execute(self.snapshot, ["SELECT SUM(i) FROM range(100000000000) t(i)"], timeout=0.05)
        event = threading.Event()
        timer = threading.Timer(0.1, event.set)
        timer.start()
        try:
            with self.assertRaises(InterruptedError):
                execute(self.snapshot, ["SELECT SUM(i) FROM range(100000000000) t(i)"], event)
        finally:
            timer.join()
        self.assertEqual(review(self.snapshot, CONTRACT, GOOD_SQL)["status"], "passed on this snapshot")

    def test_population_and_date_boundaries(self):
        sql = GOOD_SQL.replace("o.status = 'paid' AND ", "").replace("o.ordered_at < '2026-11-01'", "o.ordered_at <= '2026-11-01'")
        result = review(self.snapshot, CONTRACT, sql)
        checks = {check["id"]: check for check in result["checks"]}
        self.assertEqual(checks["population"]["status"], "issue found")
        self.assertEqual(checks["dates"]["status"], "issue found")
        for check in checks.values():
            self.assertEqual(execute(self.snapshot, [check["diagnostic_sql"]])[0]["row_count"], check["count"])

    def test_zero_measure_does_not_hide_population_loss(self):
        bundle = commerce_bundle()
        bundle["files"]["orders.csv"] = bundle["files"]["orders.csv"].replace("4,Singapore,paid,2026-10-15,50.00", "4,Singapore,paid,2026-10-15,0.00")
        snapshot = import_bundle(bundle)
        sql = GOOD_SQL.replace("WHERE ", "WHERE o.order_id != 4 AND ")
        result = review(snapshot, CONTRACT, sql)
        self.assertEqual(result["status"], "issue found")
        self.assertEqual(result["difference"]["absolute"], 0)
        self.assertEqual(result["difference"]["population"]["missing"], 1)

    def test_null_denominator_and_repair(self):
        contract = copy.deepcopy(CONTRACT)
        contract["measure"]["aggregation"] = "avg"
        sql = GOOD_SQL.replace("SUM(o.revenue)", "AVG(COALESCE(o.revenue, 0))")
        result = review(self.snapshot, contract, sql)
        self.assertEqual(result["status"], "issue found")
        self.assertEqual(next(c for c in result["checks"] if c["id"] == "nulls")["status"], "issue found")
        self.assertEqual(review(self.snapshot, contract, result["proposal"]["sql"])["status"], "passed on this snapshot")

    def test_coincidental_null_results_do_not_hide_wrong_denominator(self):
        contract = copy.deepcopy(CONTRACT)
        contract["measure"]["aggregation"] = "avg"
        contract["groups"] = ["order_id"]
        sql = GOOD_SQL.replace("o.region", "o.order_id").replace("SUM(o.revenue)", "SUM(o.revenue) / COUNT(*)")
        result = review(self.snapshot, contract, sql)
        self.assertEqual(result["status"], "issue found", result)
        self.assertEqual(result["difference"]["groups"], [])
        self.assertIsNone(result["original"]["total"])
        check = next(c for c in result["checks"] if c["id"] == "nulls")
        self.assertEqual(check["count"], 1)
        self.assertEqual(execute(self.snapshot, [check["diagnostic_sql"]])[0]["row_count"], 1)

    def test_undeclared_paths_and_incorrect_cardinality_cannot_pass(self):
        contract = copy.deepcopy(CONTRACT)
        contract["relationships"] = []
        self.assertEqual(review(self.snapshot, contract, GOOD_SQL)["status"], "needs definition")
        contract = copy.deepcopy(CONTRACT)
        contract["relationships"][0]["cardinality"] = "one-to-one"
        self.assertEqual(review(self.snapshot, contract, GOOD_SQL)["status"], "needs definition")
        wrong = GOOD_SQL.replace("o.order_id = i.order_id", "o.revenue = i.order_id")
        self.assertEqual(review(self.snapshot, CONTRACT, wrong)["status"], "unsupported")

    def test_contract_filters_follow_declared_column_types(self):
        contract = copy.deepcopy(CONTRACT)
        contract["filters"].append({"column": "revenue", "op": ">", "value": "90"})
        sql = GOOD_SQL.replace("WHERE ", "WHERE o.revenue > '90' AND ")
        result = review(self.snapshot, contract, sql)
        self.assertEqual(result["status"], "passed on this snapshot", result)
        self.assertEqual(result["reference"]["total"], 270)
        contract["filters"][-1] = {"column": "ordered_at", "op": "=", "value": "2026-10-02"}
        sql = GOOD_SQL.replace("WHERE ", "WHERE o.ordered_at = '2026-10-02' AND ")
        self.assertEqual(review(self.snapshot, contract, sql)["status"], "passed on this snapshot")

    def test_wrapped_denominators_cannot_hide_behind_zero_results(self):
        bundle = commerce_bundle()
        for value in ("120.00", "80.00", "150.00", "50.00", "95.00", "200.00", "60.00"):
            bundle["files"]["orders.csv"] = bundle["files"]["orders.csv"].replace(value, "0.00")
        snapshot = import_bundle(bundle)
        contract = copy.deepcopy(CONTRACT)
        contract["measure"]["aggregation"] = "avg"
        for expression in ("(SUM(o.revenue) / COUNT(*)) + 0", "CAST(SUM(o.revenue) / COUNT(*) AS DOUBLE)"):
            result = review(snapshot, contract, GOOD_SQL.replace("SUM(o.revenue)", expression))
            self.assertEqual(result["status"], "issue found", result)
            self.assertEqual(result["difference"]["groups"], [])
            check = next(c for c in result["checks"] if c["id"] == "nulls")
            self.assertEqual(execute(snapshot, [check["diagnostic_sql"]])[0]["row_count"], check["count"])

    def test_large_decimals_keep_exact_cents_and_headline(self):
        bundle = commerce_bundle()
        bundle["manifest"]["tables"][0]["columns"][-1]["type"] = "DECIMAL(38,2)"
        exact = "123456789012345678901234567890123456.78"
        bundle["files"]["orders.csv"] = bundle["files"]["orders.csv"].replace("120.00", exact)
        snapshot = import_bundle(bundle)
        result = review(snapshot, CONTRACT, GOOD_SQL)
        self.assertEqual(result["status"], "passed on this snapshot", result)
        self.assertEqual(result["original"]["total"], "123456789012345678901234567890123736.78")
        hong_kong = next(row for row in result["reference"]["rows"] if row["region"] == "Hong Kong")
        self.assertEqual(hong_kong["revenue"], "123456789012345678901234567890123536.78")
        wrong = review(snapshot, CONTRACT, GOOD_SQL.replace("SUM(o.revenue)", "SUM(o.revenue) + 0.01"))
        self.assertEqual(wrong["status"], "issue found", wrong)
        self.assertEqual(wrong["difference"]["group_count"], 2)
        self.assertEqual(wrong["difference"]["absolute"], 0.02)
        for check in wrong["checks"]:
            self.assertEqual(execute(snapshot, [check["diagnostic_sql"]])[0]["row_count"], check["count"])

    def test_decimal_distinct_and_null_zero_are_numeric(self):
        bundle = commerce_bundle()
        bundle["files"]["orders.csv"] = "order_id,region,status,ordered_at,revenue\n1,A,paid,2026-10-02,1.0\n2,A,paid,2026-10-02,1.00\n3,A,paid,2026-10-02,-0.00\n4,A,paid,2026-10-02,\n"
        contract = copy.deepcopy(CONTRACT)
        contract["measure"]["aggregation"] = "count_distinct"
        contract["null_policy"] = "zero"
        snapshot = import_bundle(bundle)
        correct = "SELECT o.region,COUNT(DISTINCT COALESCE(o.revenue,0)) AS revenue FROM orders o GROUP BY o.region"
        wrong = correct.replace("COUNT(DISTINCT COALESCE(o.revenue,0))", "COUNT(o.revenue)")
        self.assertEqual(review(snapshot, contract, correct)["status"], "passed on this snapshot")
        self.assertEqual(review(snapshot, contract, wrong)["status"], "issue found")
        self.assertEqual(snapshot["tables"]["orders"]["rows"][0]["revenue"], snapshot["tables"]["orders"]["rows"][1]["revenue"])
        self.assertEqual(snapshot["tables"]["orders"]["rows"][2]["revenue"], "0.00")

    def test_rounding_and_near_boundary(self):
        harmless = review(self.snapshot, CONTRACT, GOOD_SQL.replace("SUM(o.revenue)", "SUM(o.revenue) + 0.004"))
        wrong = review(self.snapshot, CONTRACT, GOOD_SQL.replace("SUM(o.revenue)", "SUM(o.revenue) + 0.006"))
        self.assertEqual(harmless["status"], "passed on this snapshot")
        self.assertEqual(wrong["status"], "issue found")

    def test_import_validation_identity_and_bounds(self):
        self.assertEqual(import_bundle(commerce_bundle())["id"], self.snapshot["id"])
        for edit in (lambda b: b["manifest"]["tables"][0].update(name="x;drop table x"),
                     lambda b: b["files"].update({"orders.csv": "wrong,headers\n1,2"}),
                     lambda b: b["files"].update({"orders.csv": b["files"]["orders.csv"].replace("120.00", "12.001")})):
            bundle = commerce_bundle()
            edit(bundle)
            with self.assertRaises(ValueError):
                import_bundle(bundle)
        with patch("queryproof.importer.MAX_ROWS", 1), self.assertRaisesRegex(ValueError, "row limit"):
            import_bundle(commerce_bundle())
        with patch("queryproof.importer.MAX_BYTES", 1), self.assertRaisesRegex(ValueError, "100 MB"):
            import_bundle(commerce_bundle())

    def test_execution_failure_remains_failure(self):
        result = review(self.snapshot, CONTRACT, GOOD_SQL.replace("SUM(o.revenue)", "SUM(o.missing_column)"))
        self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
