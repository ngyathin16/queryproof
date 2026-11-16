import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from queryproof.server import make_server
from queryproof.store import Store


class PersistenceTests(unittest.TestCase):
    def test_restart_marks_unfinished_review_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            run = store.create({"snapshot_id": "snapshot", "sql": "SELECT 1", "contract": {}})
            reopened = Store(directory)
            self.assertEqual(reopened.get(run["id"])["status"], "interrupted")
            reopened.finish(run["id"], "completed", {"status": "passed on this snapshot"})
            self.assertEqual(reopened.get(run["id"])["status"], "interrupted")


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.server = make_server(cls.directory.name, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.directory.cleanup()

    def request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw.decode()

    def wait_run(self, run):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            current = self.request("/api/runs/" + run["id"])
            if current["status"] != "running":
                return current
            time.sleep(0.1)
        self.fail("Review did not finish")

    def test_review_repair_history_and_export(self):
        example = self.request("/api/examples")[0]
        snapshot = self.request("/api/snapshots", {"bundle": example["bundle"]})
        self.assertTrue(snapshot["id"])
        self.assertNotIn("rows", next(iter(snapshot["tables"].values())))
        run = self.wait_run(self.request("/api/runs", {"snapshot_id": snapshot["id"], "contract": example["contract"], "sql": example["sql"]}))
        self.assertEqual(run["status"], "completed", run)
        self.assertEqual(run["result"]["status"], "issue found")
        proposal = run["result"]["proposal"]
        self.assertTrue(proposal["sql"])
        repaired = self.wait_run(self.request("/api/runs", {"snapshot_id": snapshot["id"], "contract": example["contract"], "sql": proposal["sql"], "parent_id": run["id"]}))
        self.assertEqual(repaired["result"]["status"], "passed on this snapshot", repaired)
        self.assertEqual(self.request("/api/runs/" + run["id"])["sql"], example["sql"])
        exported = self.request(f'/api/runs/{run["id"]}/export')
        self.assertFalse(exported["contains_example_rows"])
        self.assertTrue(all(not check["examples"] for check in exported["review"]["result"]["checks"]))
        report = self.request(f'/api/runs/{run["id"]}/export?format=html')
        self.assertIn(snapshot["id"], report)
        self.assertIn("Reproduce this review", report)
        self.assertEqual(self.request("/api/snapshots/" + snapshot["id"])["id"], snapshot["id"])

    def test_cancel_cannot_later_be_completed(self):
        example = self.request("/api/examples")[0]
        snapshot = self.request("/api/snapshots", {"bundle": example["bundle"]})
        run = self.request("/api/runs", {"snapshot_id": snapshot["id"], "contract": example["contract"], "sql": example["sql"]})
        cancelled = self.request(f'/api/runs/{run["id"]}/cancel', {})
        self.assertEqual(cancelled["status"], "interrupted")
        deadline = time.monotonic() + 10
        while self.server.app.active and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.request("/api/runs/" + run["id"])["status"], "interrupted")

    def test_local_request_boundary(self):
        for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request("/api/examples", headers=headers)
            self.assertEqual(caught.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/snapshots", {"bundle": {"manifest": {"tables": []}, "files": {}}})
        self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
