"""Cross-check frozen known solutions directly, without invoking the detector."""
import json
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate import check_groups, check_population, load_cases
from queryproof.importer import import_bundle
from queryproof.sql import validate
from queryproof.worker import execute


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["v1", "v2"], default="v1")
    args = parser.parse_args()
    manifest, cases = load_cases(args.suite)
    records = []
    for split in ["development", "evaluation"]:
        for case in cases[split]:
            if not case["repairable"]:
                continue
            record = {"id": case["id"]}
            try:
                snapshot = import_bundle(case["bundle"])
                sql = case["known_solution"]
                validate(sql, snapshot["tables"])
                result = execute(snapshot, [sql])[0]
                record["groups_match"] = check_groups(case, {"original": result})
                record["population_matches"] = check_population(case, snapshot, sql)
                record["passed"] = record["groups_match"] and record["population_matches"]
            except Exception as exc:
                record.update(passed=False, error=str(exc))
            records.append(record)
    output = {"manifest_sha256": manifest["sha256"], "method": "Execute each known solution in restricted DuckDB, compare independent row-oracle groups and selected base population. Does not invoke engine.review.", "passed": sum(r["passed"] for r in records), "total": len(records), "records": records}
    destination = ROOT / ("evaluation/known-solution-check.json" if args.suite == "v1" else "evaluation/v2/known-solution-check.json")
    destination.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output))
    if output["passed"] != output["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
