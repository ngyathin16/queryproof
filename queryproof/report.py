import copy
import html
import importlib.metadata
import platform
from .store import encode


def packet(run, snapshot, include_examples=False):
    evidence = copy.deepcopy(run)
    # Trial messages may contain diagnostic rows: export only the bounded result summary.
    evidence.pop("trials", None)
    if not include_examples and evidence.get("result"):
        for check in evidence["result"].get("checks", []):
            check["examples"] = []
    return {"format": "queryproof-review-v1", "contains_example_rows": include_examples,
            "dataset": {"id": snapshot["id"], "name": snapshot.get("name", "Imported snapshot"),
                        "tables": {name: {"columns": table["columns"], "row_count": len(table["rows"])}
                                   for name, table in snapshot["tables"].items()}},
            "review": evidence, "versions": {"queryproof": "0.1.0", "python": platform.python_version(),
                **{name: importlib.metadata.version(name) for name in ("duckdb", "sqlglot")}},
            "reproduce": ["Clone QueryProof and run uv sync --frozen.",
                          "Run npm ci and npm run build in ui, then uv run queryproof from the repository root.",
                          "Load the same bundled example or reimport your original CSV bundle; match the dataset SHA-256 identity.",
                          "Paste this packet's contract and SQL, run review, and compare the complete grouped results.",
                          "Input CSV files are excluded. An imported snapshot cannot be reconstructed from this report alone."]}


def render_html(data):
    review = data["review"]
    result = review.get("result") or {}
    esc = lambda value: html.escape(str(value))
    checks = "".join(f'<section><h2>{esc(c.get("title", c.get("id")))}</h2><p><strong>{esc(c.get("status"))}</strong> — {esc(c.get("explanation"))}</p><p>Contract: {esc(c.get("contract_clause", ""))}</p><pre>{esc(c.get("diagnostic_sql", ""))}</pre><p>Witness count: {esc(c.get("count", 0))}; examples truncated: {esc(c.get("truncated", False))}</p>{"<pre>" + esc(encode(c.get("examples"))) + "</pre>" if data["contains_example_rows"] else ""}</section>' for c in result.get("checks", []))
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>QueryProof review</title>
<style>body{{font:17px/1.6 system-ui;max-width:980px;margin:40px auto;padding:24px;color:#243e36;background:#faf8f2}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eceee6;padding:18px}}section{{border-top:1px solid #ccd4cd;margin-top:28px}}h1,h2{{line-height:1.2}}</style>
<main><p>QUERYPROOF · REPRODUCIBLE REVIEW</p><h1>{esc(review["contract"].get("name", "Metric review"))}</h1><p>{esc(result.get("status", review["status"]))} · {esc(review["created_at"])}</p>
<p>Snapshot: {esc(data["dataset"]["id"])}</p><p>Example-row export: {"explicitly included" if data["contains_example_rows"] else "excluded (default)"}.</p>
<h2>SQL reviewed</h2><pre>{esc(review["sql"])}</pre>{checks}<h2>Reproduce this review</h2><ol>{"".join("<li>"+esc(step)+"</li>" for step in data["reproduce"])}</ol>
<h2>Complete evidence packet</h2><pre>{esc(encode(data))}</pre></main></html>'''
