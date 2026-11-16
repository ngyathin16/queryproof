# Verification

Status: working local preview, **not full PRD acceptance**, 16 November 2026 (Asia/Hong_Kong).

## Reproducible implementation

The final engine, provider and evaluation implementation is pinned to commit `7fd67e20442c7c4febdd80a0a44c6f8162c2b6c8`. Later commits attach verification artifacts, documentation, and the interface redesign; the pinned engine, providers, and evaluator are unchanged. Runtime versions: Python 3.12.13 on Windows, Python 3.12.3 on Ubuntu/WSL, DuckDB 2.0.0, SQLGlot 30.31.0, Node 24.14.0, React 19.3.1, Vite 8.3.8 and TypeScript 6.0.3. Dependencies are locked; `.gitattributes` preserves evaluation JSON hashes across checkouts.

An independent local clone was created from this Git revision on a second drive, with no copied dependencies. `uv sync --frozen`, `npm ci`, `npm run build`, and all **41 Python tests** passed on Windows. A separate Linux virtual environment in Ubuntu/WSL also installed the locked dependencies and passed all **41 tests** against the clean clone. The interface build includes strict TypeScript checks. No account, API credential or model was needed for this verification. The hosted adapter was tested against a local protocol test service with a dummy key; **no hosted live inference or paid call was tested**.

The test suite covers actual CSV imports and malformed input, immutable review/export history through HTTP, cancellation and restart interruption, request-origin rejection, SQL rejection before execution, runtime external-access restrictions, timeout/recovery, preaggregated branches, grouped results, population/date/null mistakes, provider error boundaries and consent binding. Numerical regressions cover 38-digit decimals, distinct decimal equality, wrapped denominator expressions, rounding boundaries and exact large-number display.

## Browser evidence

The real built interface was checked in Microsoft Edge 157.0.4341.57 using Playwright 1.65.0 and axe-core 4.14.0 on Windows. The reproducible script is `cd ui && npm run verify` against a running server; use a separate data directory for test history.

The redesigned graphite interface passed **21 workflow checks**, including keyboard operation of the dataset, metric-definition, and diagnostic-SQL disclosures. [Browser results](browser-verification.json) record initial, incorrect-review, repaired-review and assistance-panel views at **360, 768 and 1440 px**, with no horizontal page overflow or automated WCAG-tagged findings. Workflow checks exercise the real API: import, review, witness inspection, repair execution before acceptance, history, stale SQL/contract handling, missing definitions, reload, JSON/HTML export and cancellation. The provider-change consent check explicitly intercepts configuration responses and verifies no assistance request is dispatched; it is not live hosted-provider evidence. No browser exceptions or external asset requests were observed. Automated checks are not accessibility certification or human usability testing.

The redesign was compared with two alternative visual studies before implementation; [design decisions](DESIGN.md) describe the selected direction. Screenshots are in [screenshots](screenshots/). The [captioned walkthrough](walkthrough.mp4) records the actual fixture workflow, with [captions](walkthrough.vtt), [capture metadata](walkthrough-capture.json) and [reproduction instructions](WALKTHROUGH.md). It contains a 72-second scripted story; the encoded video is 80.68 seconds including the recorder tail. No mock success response or prerecorded chart drives the application.

## Evaluation

The [manifest](../evaluation/manifest.json) froze 60 development and 60 evaluation cases before initial detector execution. The final deterministic checks match **120/120 expected statuses**, including all 24 incorrect evaluation cases, 12 valid cases, 12 missing-definition cases and 12 unsupported cases. The original development denominator miss and exploratory model failures remain in the earlier results. Both splits are now regression evidence.

The [48 declared repair solutions](../evaluation/known-solution-check.json) were separately executed inside the supported grammar and compared with independently specified grouped and population expectations. They do not rely on the detector declaring its own repair successful. See [evaluation methodology](../evaluation/README.md), expected results and raw traces for the actual scope.

The [completed model comparison](../evaluation/results/final-pinned/model-summary.json) uses the same local Qwen model and task/settings, three trials for each of 24 repairable cases in each mode. Hidden grading examines complete groups and entity populations, and failures remain in the denominator. Its [source check](../evaluation/results/final-pinned/completion.json) confirms the pinned runtime/evaluator files did not change. All **144 unique scheduled trials** are retained.

| Mode | Successful executed repairs | Failed assistance | Aggregate assistance time | Input / output tokens |
| --- | ---: | ---: | ---: | ---: |
| Without diagnostic tools | 24 / 72 | 9 / 72 | 161.833 s | 55,101 / 8,442 |
| With QueryProof tools | 43 / 72 | 16 / 72 | 425.420 s | 597,808 / 15,618 |

The tools mode includes one 60-second timeout. More repairs succeeded overall in this fixed synthetic experiment, at greater time/token cost; population-filter repairs declined from 12/18 to 8/18. This is not a general model-accuracy claim. The [full results and failure analysis](../evaluation/RESULTS.md) retain family breakdowns. The earlier exploratory run and [interrupted 39-trial attempt](../evaluation/results/pinned-interrupted/interruption.json) are preserved and explicitly distinguished from this complete run. No paid inference was used. Human explanation-rubric review remains open.

[Witness verification](../evaluation/witness-verification.json) independently re-executed **180/180 diagnostic queries**, matching every reported full count on its pinned snapshot.

## Performance

[Final raw benchmark](evidence/benchmark-final.json) and [separate profile](evidence/benchmark-final.profile.txt) were produced from the clean `7fd67e2` checkout. The fixture has 100,000 input rows: 20,000 orders and two 40,000-row branches, producing 80,000 joined rows and ten groups. Each timed review includes parsing, contract validation, fresh-worker startup/loading, SQL execution, independent row calculation and full comparison. CSV import is measured separately; HTTP, browser rendering and export are excluded.

The first process review took **766 ms**; 30 warm reviews had **723 ms p95**, **689 ms median**, and **662–728 ms range**. All 31 produced the expected original total, reference total and 20,000 duplicated-entity count, with **zero failed runs**. Worker resident-memory samples are retained. This meets the 3-second engine interaction target on this fixture and machine; it is not a laptop or general scale claim. Hardware: Core Ultra 9 285K, 24 logical cores, 32 GB RAM, Windows 11; the machine was shared with desktop/model work. Worker startup, IPC and loading dominate the profile. “Warm” refers to OS/import caches; each review still uses a fresh worker. “Cold” means the first process review, not a reboot or flushed caches. The earlier benchmark remains separately labeled.

## Open acceptance gates

- The synthetic suite shares concepts and fixture structure across splits. It does not meet the PRD's full structural holdout and breadth requirement. A new independently specified version is needed before any unseen-case claim.
- Contract semantics are limited to base-table measures/groups, direct declared relationship paths and UTC timestamps. Some valid broader contracts and query shapes are explicitly unsupported. Intentional alternative many-to-many grains need stronger coverage.
- Independent human review of expected outcomes and model explanations has not occurred. No analyst, service-engineer or unfamiliar-user usability study was performed; no participant feedback is invented.
- The provider comparison measures this model and bounded JSON-action protocol on synthetic tasks, not general model quality. [Local model selection](MODEL-SELECTION.md) explains why Qwen was retained and why the smaller candidate's fast failures are not a speedup.
- Linux has a sampled resident-memory watchdog rather than a hard cgroup boundary. The loopback service is not a production execution sandbox or hosted database gateway.
- No public executable backend is deployed. The public repository, screenshots and recording are source/evidence access, not a hosted application.

These gaps keep QueryProof labeled work in progress. No completed portfolio case study or ReleaseGuard implementation is claimed. ReleaseGuard remains gated on flagship acceptance.

## Verification interruptions retained

The system drive filled during development. One interrupted source write was restored byte-for-byte against its prior SHA-256, then checkpointed before further edits. Only task-generated dependencies were compacted/relocated; original project source and unrelated workspace edits were preserved.

A first parallel clean-checkout attempt failed from system memory pressure, and the WSL VM reported a crash. After unloading the unused comparison model, sequential Windows installation/build/tests and the separate Ubuntu test run passed. These infrastructure failures are not counted as successful checks. The Linux test result does not imply a Linux UI build or browser pass.
