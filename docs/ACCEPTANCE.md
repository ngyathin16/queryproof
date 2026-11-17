# Acceptance evidence: 17 November 2026

The workbench implements Q1–Q9 for its documented local, bounded analysis scope. The runtime and evaluator for this verification are pinned to `5e7e97b`. Follow the limitations below when interpreting acceptance: a successful review is conditional on the confirmed metric contract and imported snapshot.

| Requirement | Implemented behavior and evidence |
| --- | --- |
| Q1: imports | CSV manifests, types, row counts, content identity and import limits; real HTTP/browser import checks and malformed-input tests. Overflowing doubles, time-bearing DATE values and invalid empty decimal schemas are rejected. |
| Q2: metric intent | Explicit grain/key, measure/ratio definitions, dimensions, declared relationship paths and cardinality, population, UTC interval, units, nulls and numerical tolerances. Missing meaning remains `needs definition`. |
| Q3: bounded SQL | Explicit SQLGlot AST allowlist; two aggregate CTEs and two INNER/LEFT joins; restricted DuckDB worker with external access disabled, execution timeout and memory supervision. |
| Q4: separate checks | Grain, population, dates, null/denominator behavior and complete grouped results are independently reported. Zero-valued numerators no longer hide a changed ratio denominator. |
| Q5: inspectable evidence | Each issue carries SQL location, contract clause, diagnostic SQL, full count and at most 20 examples. All 180 witnesses in the structural suite reproduce their full counts. |
| Q6: revisions/reference | Immutable SQL/contract/snapshot versions; independent row/Decimal reference; complete groups and populations compared before truncation. All 48 declared solutions across the development/new evaluation split pass independent execution grading. |
| Q7: exports | Real JSON and standalone HTML downloads with hashes, inputs, checks, tool versions and reproduction instructions; example-row export requires explicit selection. |
| Q8: live model | Local Qwen through Ollama, bounded diagnostic tools, same SQL restrictions, model/time/token/activity disclosure and visible provider failure. The refreshed 144-trial comparison and prose review are linked from verification. |
| Q9: lifecycle | Real cancellation/worker termination, stale-current-result handling, reload/history/reset and restart interruption covered through service and browser boundaries. |

## Evaluation interpretation

Version two preserves the original 60 development cases and freezes 60 new evaluation cases before execution. Evaluation differs structurally: signed ledger sums, compound attribution grains, subscription ratios, device/cohort averages with zero substitution, distinct inventory labels and session averages; joins include repeated relationship keys, preaggregation and dimensions. Every family has six incorrect cases, plus 12 valid, 12 underspecified and 12 unsupported cases.

The first execution detected 23/24 incorrect cases (six each for grain, population and dates; five for nulls), made no false issue finding on the 12 valid cases and never verified the 24 undefined/unsupported cases. That meets the numerical detector targets while exposing a real denominator miss. The retained fix yields 24/24 on subsequent regression execution; those inspected cases are no longer unseen evidence. Existing version-one regression outcomes remain 120/120.

The two fixture sets contain 120 cases total, not 180 independent holdout cases. Results from historical and refreshed model experiments must not be added together into one experiment. Expected outputs come from an independent row implementation, permitted by the PRD; they are agent-authored, not human-reviewed or customer data.

## Limits and external validation

- Measures and grouping dimensions belong to the declared base table. Relationship paths can traverse earlier joined tables, but this does not make arbitrary cross-table metric contracts supported. Choose an imported bridge table as the base for a legitimate compound many-to-many grain.
- Timestamp interpretation is UTC. Other timezones are explicitly unsupported and must be normalized and confirmed by the reviewer.
- The Linux memory guard samples resident memory; it is not a hard cgroup sandbox. The application remains localhost-only and is not a hosted query gateway.
- No representative human usability participants were available. Browser automation and the explanation review are agent checks, explicitly distinguished from human validation.
- Performance is measured on the declared desktop environment, not an untested laptop. No production-scale or generalized model-accuracy claim is made.
- Publication provides source, screenshots and a captioned recording. No public executable backend is claimed.

These limits must remain visible in any portfolio case study. A broader contract language, timezone support or hosted execution would require new implementation and acceptance evidence.
