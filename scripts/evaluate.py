"""Run frozen cases, retaining complete failures. No success is inferred from model prose."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_cases(suite="v1"):
    folder = ROOT / "evaluation" if suite == "v1" else ROOT / "evaluation" / suite
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    raw = (folder / "cases.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["sha256"]:
        raise ValueError("Frozen case hash mismatch. Do not overwrite evaluation evidence.")
    return manifest, json.loads(raw)


def check_groups(case, result):
    contract = case["contract"]
    expected = case["expected"]["groups"]
    actual = result.get("original") or {}
    rows = actual.get("rows", [])
    columns = actual.get("columns", [])
    if rows and isinstance(rows[0], list):
        rows = [dict(zip(columns, row)) for row in rows]
    keys = contract["groups"]
    alias = contract["measure"]["alias"]
    indexed = {tuple(row.get(k) for k in keys): row for row in rows}
    if len(indexed) != len(rows) or len(indexed) != len(expected):
        return False
    tolerance = Decimal(str(contract["absolute_tolerance"]))
    relative = Decimal(str(contract["relative_tolerance"]))
    scale = Decimal(10) ** -contract["decimal_scale"]
    for reference in expected:
        key = tuple(reference[k] for k in keys)
        if key not in indexed or alias not in indexed[key]:
            return False
        wanted, found = reference[alias], indexed[key][alias]
        if wanted is None or found is None:
            if wanted != found:
                return False
        else:
            a, b = Decimal(str(wanted)), Decimal(str(found))
            rounding = ROUND_HALF_EVEN if contract["rounding"] == "half_even" else ROUND_HALF_UP
            a, b = a.quantize(scale, rounding=rounding), b.quantize(scale, rounding=rounding)
            if abs(a - b) > max(tolerance, abs(a) * relative):
                return False
    return True


def check_population(case, snapshot, sql):
    from sqlglot import exp, parse_one
    from queryproof.worker import execute

    tree = parse_one(sql, read="duckdb")
    base = tree.args.get("from_")
    if base is None or not isinstance(base.this, exp.Table) or base.this.name != case["contract"]["base_table"]:
        return False
    alias = base.this.alias_or_name
    tree.set("expressions", [exp.column(key, table=alias) for key in case["contract"]["stable_key"]])
    tree.set("group", None)
    tree.set("order", None)
    values = execute(snapshot, [tree.sql(dialect="duckdb")])[0]
    rows = values["rows"]
    if rows and isinstance(rows[0], dict):
        population = {tuple(row[key] for key in case["contract"]["stable_key"]) for row in rows}
    else:
        population = {tuple(row) for row in rows}
    expected = {tuple(row) for row in case["expected"]["population"]}
    return population == expected


def summarize(records):
    confusion = Counter((r["expected_status"], r["actual_status"]) for r in records)
    return {"cases": len(records), "matched_status": sum(r["expected_status"] == r["actual_status"] for r in records),
            "confusion": [{"expected": e, "actual": a, "count": n} for (e, a), n in sorted(confusion.items())],
            "missed": [r["id"] for r in records if r["expected_status"] != r["actual_status"]],
            "incorrect_detection_by_family": {family: {"detected": sum(r["actual_status"] == "issue found" for r in records if r["family"] == family), "total": sum(r["family"] == family for r in records)} for family in ["join", "population", "date", "null"]}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["development", "evaluation"], default="evaluation")
    parser.add_argument("--suite", choices=["v1", "v2"], default="v1")
    parser.add_argument("--models", action="store_true", help="Run all 144 real local-model trials (may take over an hour).")
    parser.add_argument("--smoke", action="store_true", help="Run one repair case once per model mode; not the acceptance comparison.")
    parser.add_argument("--output", default=None)
    parser.add_argument("--allow-hosted", action="store_true", help="Explicitly allow billed hosted inference; configure provider account spending limits first.")
    args = parser.parse_args()
    from queryproof.engine import review
    from queryproof.importer import import_bundle
    from queryproof.provider import assist, configuration

    if (args.models or args.smoke) and not configuration()["local"] and not args.allow_hosted:
        parser.error("Hosted inference can incur charges. Set account spending limits and explicitly add --allow-hosted to run it.")

    manifest, dataset = load_cases(args.suite)
    output = Path(args.output) if args.output else ROOT / "evaluation/results" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.split)
    output.mkdir(parents=True, exist_ok=False)
    sources = [*sorted((ROOT / "queryproof").glob("*.py")), Path(__file__).resolve(), ROOT / "evaluation/generate_cases.py", ROOT / "evaluation/generate_v2.py"]
    source_hashes = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    tracked = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True)
    meta = {"started_at": datetime.now(timezone.utc).isoformat(), "manifest_sha256": manifest["sha256"], "source_sha256": source_hashes, "git_revision": revision.stdout.strip() if revision.returncode == 0 else None, "tracked_changes": tracked.stdout.splitlines(), "python": platform.python_version(), "platform": platform.platform(), "split": args.split, "case_count": len(dataset[args.split]), "provider": configuration() if args.models or args.smoke else None, "evaluation_status": "development regression evidence after first inspection; no unseen claim"}
    if meta["provider"] and meta["provider"]["local"]:
        try:
            with urllib.request.urlopen(meta["provider"]["endpoint"] + "/api/tags", timeout=2) as response:
                models = json.load(response)["models"]
            meta["provider"]["installed_model"] = next((m for m in models if m["name"] == meta["provider"]["model"]), None)
            with urllib.request.urlopen(meta["provider"]["endpoint"] + "/api/version", timeout=2) as response:
                meta["provider"]["server_version"] = json.load(response)
        except (OSError, ValueError, KeyError) as exc:
            meta["provider"]["metadata_error"] = str(exc)
    (output / "environment.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    records = []
    snapshots = {}
    reviews = {}
    for case in dataset[args.split]:
        started = time.monotonic()
        try:
            snapshot = import_bundle(case["bundle"])
            snapshots[case["id"]] = snapshot
            result = review(snapshot, case["contract"], case["sql"])
            reviews[case["id"]] = result
            record = {"id": case["id"], "family": case["family"], "expected_status": case["expected_status"], "actual_status": result["status"], "elapsed_ms": round((time.monotonic()-started)*1000), "result": result}
        except Exception as exc:
            record = {"id": case["id"], "family": case["family"], "expected_status": case["expected_status"], "actual_status": "failed", "error": str(exc)}
        records.append(record)
        with (output / "deterministic.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, default=str) + "\n")
        print(case["id"], record["actual_status"], flush=True)
    summary = summarize(records)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)
    if args.models or args.smoke:
        repairable = [c for c in dataset[args.split] if c["repairable"]]
        if args.smoke:
            repairable = repairable[:1]
        trials = 1 if args.smoke else 3
        model_records = []
        for case in repairable:
            snapshot = snapshots.get(case["id"])
            for trial in range(trials):
                for mode in ["baseline", "tools"]:
                    if snapshot is None:
                        result = {"status": "failed", "error": "Import failed; retained in denominator."}
                    else:
                        try:
                            result = assist(snapshot, case["contract"], case["sql"], reviews.get(case["id"], {}), mode=mode, seed=trial)
                        except Exception as exc:
                            result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                    proposal = result.get("proposal")
                    grade = {"groups_match": False, "population_matches": False, "success": False}
                    if proposal:
                        try:
                            checked = proposal["review"]
                            grade["groups_match"] = check_groups(case, checked)
                            grade["population_matches"] = checked["status"] not in {"unsupported", "failed", "interrupted", "needs definition"} and check_population(case, snapshot, proposal["sql"])
                            grade["semantic_checks_passed"] = checked["status"] == "passed on this snapshot"
                            grade["success"] = grade["groups_match"] and grade["population_matches"] and grade["semantic_checks_passed"]
                        except Exception as exc:
                            grade["error"] = str(exc)
                    record = {"case_id": case["id"], "mode": mode, "trial": trial, "grade": grade, "assistance": result}
                    model_records.append(record)
                    with (output / "model-trials.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(record, default=str) + "\n")
                    print("model", case["id"], trial, mode, grade["success"], result.get("elapsed_ms"), flush=True)
        model_summary = {"complete_acceptance_comparison": not args.smoke and len(model_records) == 144, "cases": len(repairable), "trials_per_case_per_mode": trials, "modes": {mode: {"successful_repairs": sum(r["grade"]["success"] for r in model_records if r["mode"] == mode), "trials": sum(r["mode"] == mode for r in model_records), "failed_assistance": sum(r["assistance"]["status"] != "completed" for r in model_records if r["mode"] == mode), "total_elapsed_ms": sum(r["assistance"].get("elapsed_ms", 0) for r in model_records if r["mode"] == mode), "reported_input_tokens": sum(r["assistance"].get("tokens", {}).get("input", 0) for r in model_records if r["mode"] == mode), "reported_output_tokens": sum(r["assistance"].get("tokens", {}).get("output", 0) for r in model_records if r["mode"] == mode), "unreported_usage_trials": sum(not r["assistance"].get("tokens", {}).get("reported", False) for r in model_records if r["mode"] == mode)} for mode in ["baseline", "tools"]}, "human_explanation_review": "not performed; automatic numeric/citation checks only"}
        (output / "model-summary.json").write_text(json.dumps(model_summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(model_summary), flush=True)
    changed = [path for path, digest in source_hashes.items() if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest]
    (output / "completion.json").write_text(json.dumps({"finished_at": datetime.now(timezone.utc).isoformat(), "source_unchanged": not changed, "changed_sources": changed}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
