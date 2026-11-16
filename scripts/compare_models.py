"""Development-only local model selection; never repurpose this as unseen accuracy."""
import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from evaluate import ROOT, check_groups, check_population, load_cases
from queryproof.engine import review
from queryproof.importer import import_bundle
from queryproof.provider import assist, configuration


def ollama(path, payload=None):
    endpoint = configuration()["endpoint"]
    request = urllib.request.Request(endpoint + path, data=None if payload is None else json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def machine_gpu():
    run = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv,noheader"], capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs=2, default=["qwen3.5:9b", "lfm2.5:8b"])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--output", default="evaluation/model-selection")
    args = parser.parse_args()
    os.environ["QUERYPROOF_PROVIDER"] = "ollama"
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    manifest, dataset = load_cases()
    cases = []
    for family in ["join", "population", "date", "null"]:
        family_cases = [case for case in dataset["development"] if case["family"] == family]
        cases.extend([family_cases[0], family_cases[-1]])
    source_paths = [*sorted((ROOT / "queryproof").glob("*.py")), Path(__file__).resolve(), ROOT / "scripts/evaluate.py"]
    sources = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    environment = {"started_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(), "platform": platform.platform(),
                   "cpu": platform.processor(), "logical_cpus": os.cpu_count(), "gpu_before": machine_gpu(),
                   "git_revision": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                   "ollama_version": ollama("/api/version"), "models": {m["name"]: m for m in ollama("/api/tags")["models"] if m["name"] in args.models},
                   "cases": [case["id"] for case in cases], "manifest_sha256": manifest["sha256"], "source_sha256": sources,
                   "decision_rule": "Prefer the smaller local model if it matches or exceeds successful executed repairs on this development sample and has lower median latency. Otherwise retain the existing model. A small synthetic sample cannot establish general model superiority.",
                   "settings": {"mode": "tools", "trials_per_case": args.trials, "temperature": 0, "seeds": list(range(args.trials)), "think": False, "context": 8192, "output_tokens": 2048, "tool_calls": 8, "seconds": 60},
                   "timing": "End-to-end assist() wall time, includes model rounds and deterministic tool execution. Hidden grading runs afterwards. Models are preloaded once; each case/trial alternates model order to reduce drift. Failures remain in denominator and latency summaries.",
                   "limitations": "Development cases only, selected by fixed first/last case within each family before trials. Agent-written synthetic cases, no human explanation review. Shared desktop and browser services; no concurrent evaluation inference requested."}
    (output / "environment.json").write_text(json.dumps(environment, indent=2), encoding="utf-8")
    warmups = []
    for model in args.models:
        start = time.monotonic()
        response = ollama("/api/chat", {"model": model, "messages": [{"role": "user", "content": "Return only JSON: {\"ready\":true}"}], "stream": False, "format": "json", "think": False, "keep_alive": "10m", "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 32}})
        warmups.append({"model": model, "ms": (time.monotonic() - start) * 1000, "response": response, "loaded_models": ollama("/api/ps"), "gpu": machine_gpu()})
    (output / "warmups.json").write_text(json.dumps(warmups, indent=2), encoding="utf-8")
    records = []
    for case_index, case in enumerate(cases):
        snapshot = import_bundle(case["bundle"])
        original = review(snapshot, case["contract"], case["sql"])
        for trial in range(args.trials):
            models = args.models if (case_index + trial) % 2 == 0 else list(reversed(args.models))
            for model in models:
                started = time.monotonic()
                result = assist(snapshot, case["contract"], case["sql"], original, mode="tools", model=model, seed=trial)
                elapsed_ms = (time.monotonic() - started) * 1000
                proposal = result.get("proposal")
                grade = {"groups_match": False, "population_matches": False, "success": False}
                if proposal:
                    try:
                        checked = proposal["review"]
                        grade["groups_match"] = check_groups(case, checked)
                        grade["population_matches"] = checked["status"] not in {"unsupported", "failed", "interrupted", "needs definition"} and check_population(case, snapshot, proposal["sql"])
                        grade["success"] = grade["groups_match"] and grade["population_matches"]
                    except Exception as error:
                        grade["error"] = str(error)
                record = {"model": model, "case_id": case["id"], "family": case["family"], "trial": trial, "wall_ms": elapsed_ms, "grade": grade, "assistance": result,
                          "loaded_models": ollama("/api/ps"), "gpu": machine_gpu()}
                records.append(record)
                with (output / "trials.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record) + "\n")
                print(model, case["id"], trial, grade["success"], round(elapsed_ms), result.get("error", ""), flush=True)
    summaries = {}
    for model in args.models:
        selected = [r for r in records if r["model"] == model]
        elapsed = [r["wall_ms"] for r in selected]
        summaries[model] = {"trials": len(selected), "successful_repairs": sum(r["grade"]["success"] for r in selected),
                            "failed_assistance": sum(r["assistance"]["status"] != "completed" for r in selected), "median_ms": statistics.median(elapsed), "range_ms": [min(elapsed), max(elapsed)],
                            "input_tokens": sum(r["assistance"]["tokens"]["input"] for r in selected), "output_tokens": sum(r["assistance"]["tokens"]["output"] for r in selected),
                            "by_family": {family: {"successes": sum(r["grade"]["success"] for r in selected if r["family"] == family), "trials": sum(r["family"] == family for r in selected)} for family in ["join", "population", "date", "null"]}}
    first, second = (summaries[model] for model in args.models)
    selected_model = args.models[1] if second["successful_repairs"] >= first["successful_repairs"] and second["median_ms"] < first["median_ms"] else args.models[0]
    changed = [path for path, digest in sources.items() if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest]
    summary = {"finished_at": datetime.now(timezone.utc).isoformat(), "selected_model": selected_model, "source_unchanged": not changed, "changed_sources": changed, "models": summaries,
               "interpretation": "Development selection evidence only. Same executed hidden group/population grader as full evaluation; no claim about unseen accuracy or human explanation quality."}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
