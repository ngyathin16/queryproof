"""Measure completed deterministic reviews, retaining failures in the report."""
import argparse
import copy
import cProfile
import io
import json
import math
import os
import platform
import pstats
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from queryproof.engine import review
from queryproof.fixtures import CONTRACT, BAD_SQL, commerce_bundle
from queryproof.importer import import_bundle


def fixture():
    bundle = commerce_bundle()
    bundle["manifest"]["name"] = "100,000-row two-branch fixture (20,000 orders; 40,000 items; 40,000 touches)"
    bundle["files"]["orders.csv"] = "order_id,region,status,ordered_at,revenue\n" + "".join(
        f"{index},Region {index % 10},paid,2026-10-15,100.00\n" for index in range(1, 20_001))
    for name, key in (("items", "item_id"), ("touches", "touch_id")):
        bundle["files"][name + ".csv"] = key + ",order_id\n" + "".join(
            f"{index * 2 + offset},{index}\n" for index in range(1, 20_001) for offset in (0, 1))
    return bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--output", default="docs/evidence/benchmark-windows.json")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("runs must be positive")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    imported_at = time.perf_counter()
    snapshot = import_bundle(fixture())
    import_ms = (time.perf_counter() - imported_at) * 1000
    samples = []
    for index in range(args.runs + 1):
        started = time.perf_counter()
        result = review(snapshot, copy.deepcopy(CONTRACT), BAD_SQL)
        elapsed = (time.perf_counter() - started) * 1000
        correct = result["status"] == "issue found" and result.get("original", {}).get("total") == 8_000_000 and result.get("reference", {}).get("total") == 2_000_000 and result["checks"][0]["count"] == 20_000
        sample = {"kind": "cold" if index == 0 else "warm", "index": index, "ms": elapsed, "correct": correct, "status": result["status"], "worker_peak_rss_bytes": result.get("worker_peak_rss_bytes")}
        if not correct:
            sample["checks"] = result["checks"]
        samples.append(sample)
        print(f"{sample['kind']} {index}: {elapsed:.1f} ms, correct={correct}", flush=True)
    profiler = cProfile.Profile()
    profiler.runcall(review, snapshot, CONTRACT, BAD_SQL)
    profile = io.StringIO()
    pstats.Stats(profiler, stream=profile).strip_dirs().sort_stats("cumulative").print_stats(30)
    output.with_suffix(".profile.txt").write_text(profile.getvalue(), encoding="utf-8")
    warm = [sample["ms"] for sample in samples if sample["kind"] == "warm"]
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_under_test": "Completed deterministic review p95 <= 3000ms over 30 warm runs on this explicit 100,000-row synthetic fixture.",
        "environment": {"os": platform.platform(), "python": platform.python_version(), "processor": platform.processor(), "logical_cpus": os.cpu_count(), "load_average": os.getloadavg() if hasattr(os, "getloadavg") else None},
        "conditions": "Shared development machine; other application/model/browser processes may be active. No exclusive CPU reservation. Each review starts a fresh isolated worker; warm refers to OS/import cache. Cold is first review in this process, not a reboot or flushed OS cache.",
        "timed_region": "engine.review including grammar, contract validation, worker startup, full snapshot IPC/loading, both SQL queries, independent row oracle, full grouped comparison and witnesses. CSV import measured separately. Browser/HTTP/export not timed.",
        "fixture": {"seed": "formula-v1", "snapshot_id": snapshot["id"], "rows": snapshot["row_count"], "base_rows": 20000, "branch_rows": [40000, 40000], "groups": 10, "join_output_rows": 80000, "input_bytes": snapshot["input_bytes"], "expected_original_total": 8000000, "expected_reference_total": 2000000, "expected_duplicated_entities": 20000},
        "import_ms": import_ms, "cold_ms": samples[0]["ms"], "warm_count": len(warm),
        "warm_p95_ms": sorted(warm)[math.ceil(0.95 * len(warm)) - 1], "warm_median_ms": statistics.median(warm), "warm_range_ms": [min(warm), max(warm)],
        "failed_runs": sum(not sample["correct"] for sample in samples), "samples": samples,
        "limiter_evidence": "Separate untimed cProfile in adjacent .profile.txt; subprocess communicate includes worker import/loading/execution. No before/after speedup claim.",
    }
    report["target_met"] = report["warm_count"] >= 30 and report["failed_runs"] == 0 and report["warm_p95_ms"] <= 3000
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("warm_p95_ms", "warm_median_ms", "warm_range_ms", "failed_runs", "target_met")}, indent=2))


if __name__ == "__main__":
    main()
