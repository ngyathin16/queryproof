"""Re-execute each emitted diagnostic query against its immutable case snapshot."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source))
    from queryproof.importer import import_bundle
    from queryproof.worker import execute

    frozen = (args.source / "evaluation/cases.json").read_bytes()
    cases = {case["id"]: case for case in json.loads(frozen)["evaluation"]}
    records = []
    for line in args.results.read_text(encoding="utf-8").splitlines():
        observed = json.loads(line)
        checks = [check for check in observed.get("result", {}).get("checks", []) if check.get("diagnostic_sql")]
        if not checks:
            continue
        snapshot = import_bundle(cases[observed["id"]]["bundle"])
        for check in checks:
            record = {"case_id": observed["id"], "check_id": check["id"], "expected_count": check["count"], "diagnostic_sql": check["diagnostic_sql"]}
            try:
                actual = execute(snapshot, [check["diagnostic_sql"]])[0]
                record["observed_count"] = actual["row_count"]
                record["passed"] = actual["row_count"] == check["count"]
            except Exception as exc:
                record.update(passed=False, error=str(exc))
            records.append(record)
    output = {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.source, text=True).strip(), "manifest_sha256": hashlib.sha256(frozen).hexdigest(), "method": "Each emitted diagnostic query is independently re-executed in the restricted worker; returned full row count is compared with the finding count. No detector is called.", "passed": sum(r["passed"] for r in records), "total": len(records), "records": records}
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": output["passed"], "total": output["total"], "failures": [r for r in records if not r["passed"]]}))
    if output["passed"] != output["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
