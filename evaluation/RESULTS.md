# Recorded evaluation results

**17 November update:** The [new structural suite](v2/manifest.json) first detected 23/24 incorrect analyses with no false issues on 12 valid cases and no verification of 24 underspecified/unsupported cases. Its denominator miss is preserved in [first execution](v2/first-execution/summary.json); the fix yields [60/60 regression statuses](v2/pinned-model-comparison/summary.json). The complete fresh Qwen comparison records **12/72 successful repairs without tools and 57/72 with tools**, with all failures retained. [Raw trials](v2/pinned-model-comparison/model-trials.jsonl), [summary](v2/pinned-model-comparison/model-summary.json), [agent explanation review](v2/pinned-model-comparison/explanation-review.json). Nine snapshot-correct tool repairs still had misleading explanations. Do not combine these trials with the older experiment below. See [current verification](../docs/VERIFICATION.md) for scope and source pinning.

Recorded on 16 November 2026. The final run used implementation commit `7fd67e20442c7c4febdd80a0a44c6f8162c2b6c8`. Its [environment record](results/final-pinned/environment.json) includes source hashes, the model digest, platform and versions; its [completion record](results/final-pinned/completion.json) confirms those implementation sources stayed unchanged throughout the run. A tests-only environment-isolation improvement was present as a tracked change; it did not alter the runtime or grader.

## Deterministic checks and independent evidence

| Check | Observed result | Raw evidence |
| --- | --- | --- |
| Frozen evaluation statuses | 60/60 matched; all 24 incorrect cases detected, six in each family; no valid case flagged | [Summary](results/final-pinned/summary.json), [all outcomes](results/final-pinned/deterministic.jsonl) |
| Development statuses | 60/60 matched after the all-NULL denominator correction | [Summary](results/final-development/summary.json), [all outcomes](results/final-development/deterministic.jsonl) |
| Known repair solutions | 48/48 matched independently specified groups and selected entity populations inside the allowed grammar | [Solution checks](known-solution-check.json) |
| Diagnostic queries | 180/180 reproduced their emitted full witness counts on the pinned snapshots | [Witness checks](witness-verification.json) |

The [first development run](results/development-first/summary.json) missed an AVG-denominator error whose grouped outputs matched by coincidence. That failure remains in the record. The final engine checks the denominator populations directly. The evaluation cases are regression evidence after inspection; a passing run is not a new unseen-data result.

## Local model comparison

The final comparison used installed `qwen3.5:9b` Q4_K_M through Ollama 0.40.16. Each of the 24 incorrect cases ran three times in each mode, regardless of detector success. Both modes received the same task, contract, SQL and schema and used the documented 60-second/2,048-generated-token caps. Hidden grading compared complete grouped results and the selected entity population, not a model's success claim.

| Observed outcome | Without diagnostic tools | With QueryProof tools |
| --- | ---: | ---: |
| Executed repairs matching hidden expectations | 24/72 | 43/72 |
| Failed assistance calls retained in denominator | 9/72 | 16/72 |
| Sum of assistance elapsed time | 161.833 s | 425.420 s |
| Provider-reported input tokens | 55,101 | 597,808 |
| Provider-reported generated tokens | 8,442 | 15,618 |
| Trials missing usage reports | 0 | 0 |

See the [complete trial log](results/final-pinned/model-trials.jsonl) and [summary](results/final-pinned/model-summary.json). The tools mode repaired more of these synthetic cases and used more time and input tokens. This does not establish better general correctness, statistical significance, or performance on another model/provider. Temperature-zero trials often repeat the same proposal and are not independent samples. The experiment holds generated-token and time caps equal; it does not equalize total input tokens consumed by diagnostic evidence.

Failures are retained: across both modes, six trials requested unknown finding IDs, fifteen supplied numeric claims absent from executed evidence, three cited evidence they had not inspected, and one timed out. Completed but incorrect proposals also remain unsuccessful. Some calls slowed considerably during the run; the timeout was not discarded or rerun individually. These timings describe this run, not an isolated inference benchmark.

An earlier pinned attempt stopped after 39 recorded trials while the host had reported memory pressure. The process exit cause was not captured. Its [interruption record](results/pinned-interrupted/interruption.json) and [partial trials](results/pinned-interrupted/model-trials.jsonl) are preserved separately. The final comparison above is a complete new 144-trial attempt with no intervening tuning, not a selection of successful retries. The earlier [exploratory full run](results/full-model-comparison/model-summary.json) remains distinct because source files were still changing during implementation.

## Reproduce

From the repository root, with the documented dependencies and the same local model installed:

```sh
uv run python scripts/evaluate.py --split development
uv run python scripts/evaluate.py --models
uv run python evaluation/verify_oracles.py
uv run python evaluation/verify_witnesses.py --source . --results evaluation/results/final-pinned/deterministic.jsonl --output witness-rerun.json
```

The evaluator creates a new output directory, checks the frozen case hash, records the implementation revision/hashes and retains every result. Do not overwrite the frozen cases or original logs. Runtime and model outputs can vary across reruns.

## Remaining acceptance limits

The 120 cases were specified with AI assistance and independent row calculations, but have not received independent human review. They share fixture schema and concepts across splits; the stronger structural holdout requirement is not fully satisfied. Coverage still lacks several alternative grains, relationship topologies, ratios and floating-point boundary cases. No human explanation-rubric review or representative-user usability study has been performed. Read the [evaluation method and rubric](README.md) before interpreting these counts.

The hosted API adapter was tested through local protocol/error-boundary tests with dummy credentials. No hosted inference or paid evaluation was performed. The local model results do not establish hosted-provider behavior. These records support the implemented prototype; they do not close every project release gate.
