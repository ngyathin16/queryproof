"""Append-only review inputs; only lifecycle state may change."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)


class Store:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "reviews.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL,
                    result TEXT, error TEXT, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trials(id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            db.execute("UPDATE runs SET status='interrupted', error='The application restarted before this review finished.' WHERE status='running'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def snapshot(self, snapshot_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError("Snapshot not found")
        return json.loads(row["payload"])

    def save_snapshot(self, snapshot):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?)", (snapshot["id"], encode(snapshot)))

    def create(self, payload):
        run_id = uuid.uuid4().hex
        created = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES(?, 'running', ?, NULL, NULL, ?)", (run_id, encode(payload), created))
        return self.get(run_id)

    def finish(self, run_id, status, result=None, error=None):
        with self.connect() as db:
            db.execute("UPDATE runs SET status=?, result=?, error=? WHERE id=? AND status='running'",
                       (status, encode(result) if result is not None else None, error, run_id))

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError("Review not found")
            trials = db.execute("SELECT payload FROM trials WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        return {**json.loads(row["payload"]), "id": row["id"], "status": row["status"],
                "created_at": row["created_at"], "result": json.loads(row["result"]) if row["result"] else None,
                "error": row["error"], "trials": [json.loads(t["payload"]) for t in trials]}

    def recent(self):
        with self.connect() as db:
            rows = db.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT 100").fetchall()
        return [self.get(row["id"]) for row in rows]

    def save_trial(self, run_id, payload):
        trial = {**payload, "id": uuid.uuid4().hex}
        with self.connect() as db:
            db.execute("INSERT INTO trials VALUES(?,?,?,?)", (trial["id"], run_id, encode(trial), datetime.now(timezone.utc).isoformat()))
        return trial
