"""Loopback-only review API and built UI. Run with `uv run queryproof`."""
import argparse
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .store import Store, encode
from .report import packet, render_html

ROOT = Path(__file__).resolve().parent.parent
MAX_REQUEST = 105 * 1024 * 1024


class Application:
    def __init__(self, directory):
        self.store = Store(directory)
        self.active = {}
        self.lock = threading.Lock()
        self.assisting = set()

    def start(self, payload):
        from .engine import review
        snapshot = self.store.snapshot(payload["snapshot_id"])
        with self.lock:
            if self.active:
                raise ValueError("A review is running. Cancel it or wait before starting another.")
            run = self.store.create(payload)
            cancel = threading.Event()
            self.active[run["id"]] = cancel

        def execute():
            try:
                result = review(snapshot, payload["contract"], payload["sql"], cancel_event=cancel)
                status = "interrupted" if cancel.is_set() or result.get("status") == "interrupted" else "failed" if result.get("status") == "failed" else "completed"
                self.store.finish(run["id"], status, result)
            except Exception as error:
                self.store.finish(run["id"], "failed", error=str(error))
            finally:
                with self.lock:
                    self.active.pop(run["id"], None)

        threading.Thread(target=execute, daemon=True).start()
        return run

    def cancel(self, run_id):
        self.store.get(run_id)
        with self.lock:
            if run_id in self.active:
                self.active[run_id].set()
        self.store.finish(run_id, "interrupted", error="Cancelled by reviewer.")
        return self.store.get(run_id)


class Handler(BaseHTTPRequestHandler):
    def send(self, code, value, content_type="application/json; charset=utf-8", filename=None):
        body = value if isinstance(value, bytes) else (value if isinstance(value, str) else encode(value)).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def body(self):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("Send an application/json request.")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_REQUEST:
            raise ValueError("Request is empty or exceeds 105 MB; CSV input is limited to 100 MB.")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return data

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, mutate):
        try:
            host = self.headers.get("Host")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if host not in allowed:
                return self.send(403, {"error": "Only localhost requests are accepted."})
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{h}" for h in allowed}:
                return self.send(403, {"error": "Cross-origin requests are disabled."})
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self.send(403, {"error": "Cross-site requests are disabled."})
            self.route(mutate)
        except KeyError as error:
            self.send(404, {"error": str(error)})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send(400, {"error": str(error)})
        except Exception as error:
            self.send(500, {"error": str(error)})

    def route(self, mutate):
        from .fixtures import examples
        from .importer import import_bundle
        from .provider import configuration, assist
        app = self.server.app
        url = urlsplit(self.path)
        parts = url.path.strip("/").split("/")
        if not mutate and url.path == "/api/examples":
            return self.send(200, examples())
        if not mutate and url.path == "/api/provider":
            return self.send(200, configuration())
        if mutate and url.path == "/api/snapshots":
            body = self.body()
            snapshot = import_bundle(body.get("bundle"))
            app.store.save_snapshot(snapshot)
            return self.send(201, self.snapshot_summary(snapshot))
        if not mutate and len(parts) == 3 and parts[:2] == ["api", "snapshots"]:
            return self.send(200, self.snapshot_summary(app.store.snapshot(parts[2])))
        if url.path == "/api/runs":
            if not mutate:
                return self.send(200, app.store.recent())
            body = self.body()
            if not isinstance(body.get("sql"), str) or not 0 < len(body["sql"]) <= 50000:
                raise ValueError("SQL must contain between 1 and 50,000 characters.")
            if not isinstance(body.get("contract"), dict) or not isinstance(body.get("snapshot_id"), str):
                raise ValueError("Provide a snapshot_id and metric contract object.")
            payload = {key: body[key] for key in ("snapshot_id", "contract", "sql")}
            if body.get("parent_id"):
                parent = app.store.get(body["parent_id"])
                if parent["snapshot_id"] != body["snapshot_id"]:
                    raise ValueError("A revision must use its parent's snapshot.")
                payload["parent_id"] = parent["id"]
            return self.send(202, app.start(payload))
        if len(parts) >= 3 and parts[:2] == ["api", "runs"]:
            run_id = parts[2]
            run = app.store.get(run_id)
            if len(parts) == 3 and not mutate:
                return self.send(200, run)
            action = parts[3] if len(parts) == 4 else ""
            if action == "cancel" and mutate:
                self.body()
                return self.send(200, app.cancel(run_id))
            if action == "export" and not mutate:
                query = parse_qs(url.query)
                data = packet(run, app.store.snapshot(run["snapshot_id"]), query.get("examples") == ["1"])
                if query.get("format") == ["html"]:
                    return self.send(200, render_html(data), "text/html; charset=utf-8", f"queryproof-{run_id}.html")
                return self.send(200, data, filename=f"queryproof-{run_id}.json")
            if action == "assist" and mutate:
                body = self.body()
                if body.get("consent") is not True:
                    raise ValueError("Explicitly consent to sharing this review's bounded evidence with the configured model.")
                config = configuration()
                expected = {key: config[key] for key in ("provider", "model", "endpoint")}
                if body.get("expected_provider") != expected:
                    raise ValueError("Provider settings changed or were not confirmed. Review the provider details and consent again.")
                if run["status"] != "completed" or not run["result"]:
                    raise ValueError("Complete the deterministic review before requesting assistance.")
                with app.lock:
                    if app.assisting:
                        raise ValueError("Model assistance is already running.")
                    app.assisting.add(run_id)
                try:
                    trial = assist(app.store.snapshot(run["snapshot_id"]), run["contract"], run["sql"], run["result"])
                    return self.send(200, app.store.save_trial(run_id, trial))
                finally:
                    with app.lock:
                        app.assisting.discard(run_id)
        if not mutate and not url.path.startswith("/api/"):
            directory = (ROOT / "ui" / "dist").resolve()
            target = (directory / url.path.lstrip("/")).resolve()
            if target != directory and directory not in target.parents:
                return self.send(404, {"error": "Not found"})
            if target == directory:
                target = directory / "index.html"
            if target.is_file():
                return self.send(200, target.read_bytes(), mimetypes.guess_type(target)[0] or "application/octet-stream")
            if url.path == "/":
                return self.send(503, "Build the interface first: cd ui; npm ci; npm run build", "text/plain; charset=utf-8")
        self.send(404, {"error": "Not found"})

    @staticmethod
    def snapshot_summary(snapshot):
        return {**{k: v for k, v in snapshot.items() if k != "tables"}, "tables": {
            name: {"columns": table["columns"], "row_count": len(table["rows"])} for name, table in snapshot["tables"].items()}}

    def log_message(self, format, *args):
        # URLs contain run identifiers, never SQL, rows, or provider configuration.
        super().log_message(format, *args)


def make_server(directory, port=4317):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = Application(directory)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4317)
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("QUERYPROOF_DATA", ROOT / "data")))
    args = parser.parse_args()
    server = make_server(args.data_dir, args.port)
    print(f"QueryProof is running at http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        for run_id in list(server.app.active):
            server.app.cancel(run_id)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
