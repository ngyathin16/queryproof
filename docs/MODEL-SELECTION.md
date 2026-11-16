# Local model selection

Measured 16 November 2026. Keep **`qwen3.5:9b`** as the tested local default. It repaired 14 of 24 development trials; the smaller `lfm2.5:8b` repaired 0 of 24 under the same bounded dialogue. Neither result supports trusting model SQL without the deterministic review. No hosted inference or API key was used.

## Candidates and hardware

Ollama lists [LFM2.5-8B-A1B](https://ollama.com/library/lfm2.5) as a local model with tool support and a roughly 5.2 GB download. That makes it a reasonable efficiency candidate, not evidence of SQL repair ability. The installed [Qwen3.5 9B](https://ollama.com/library/qwen3.5:9b) is a Q4_K_M model with a roughly 6.6 GB download. These official pages describe model capabilities; all task outcomes below come from this application's executed trials.

Actual environment: Windows 11, Python 3.12.13, Ollama 0.40.16, 24 logical CPU cores, NVIDIA GeForce RTX 5080 with 16,303 MiB reported device memory. Both models stayed fully GPU-resident for all 48 measured trials at an 8,192-token context. Other desktop and browser processes remained active.

| Model | Installed bytes | Digest prefix | Reported resident GPU bytes |
| --- | ---: | --- | ---: |
| Qwen3.5 9B Q4_K_M | 6,550,825,550 | `56671c2ab938` | 5,862,210,928 |
| LFM2.5 8B Q4_K_M | 5,156,075,525 | `9cf756159fc2` | 5,386,734,140 |

Full model digests, runtime details and per-trial GPU snapshots are in [environment.json](../evaluation/model-selection/environment.json) and [trials.jsonl](../evaluation/model-selection/trials.jsonl). LFM's smaller download did not translate into a comparable reduction in observed GPU allocation with this runtime and context.

## Method and results

Before running, the decision rule was: choose the smaller model only if it matches or exceeds successful executed repairs and has lower median end-to-end assistance latency. Eight development cases were fixed by selecting the first and last case from each of the join, population, date and null families. Each ran three times per model, alternating model order. Both used the same prompt, tool protocol, temperature 0, trial seeds 0–2, 8-call/60-second limits and 2,048 generated-token budget. Models were preloaded; preload timing is retained separately and is not a cold-start comparison because Qwen was already resident.

The hidden grader compared complete grouped results and the selected entity population against independently specified expectations. It did not accept the model's success claim. Failed calls and incorrect proposals remain in every denominator.

| Outcome | Qwen3.5 9B | LFM2.5 8B |
| --- | ---: | ---: |
| Successful executed repairs | 14 / 24 | 0 / 24 |
| Failed assistance protocol | 4 / 24 | 14 / 24 |
| Completed but incorrect proposals | 6 / 24 | 10 / 24 |
| Median assistance time, all trials | 3.391 s | 1.664 s |
| Observed range, all trials | 0.328–17.922 s | 0.453–4.438 s |
| Reported input tokens | 178,524 | 271,927 |
| Reported output tokens | 4,850 | 10,778 |

LFM's shorter time includes quick failures, so it is **not a useful-work speedup**. There are no successful LFM repairs from which to estimate successful-repair latency. End-to-end assistance includes model generation, repeated dialogue rounds and SQL validation, rather than measuring tokens/second in isolation. Qwen also failed every selected population-filter trial; this small test is a reason to retain checks, not a claim that the default model is generally reliable.

Failures included nonexistent finding IDs, exhausting the tool-call budget, citing evidence never inspected, missing table aliases, and SQL that changed the intended population or aggregation. Raw outcomes and the machine-readable selection decision are in [summary.json](../evaluation/model-selection/summary.json).

## Reproduce and limits

```sh
ollama pull qwen3.5:9b
ollama pull lfm2.5:8b
uv run python scripts/compare_models.py --output evaluation/my-model-selection
```

Use a new output directory; the script refuses to overwrite an earlier run. The default application still needs no model. Select live assistance explicitly after starting Ollama. `QUERYPROOF_MODEL` can select another installed model; it has not earned these results merely by being configurable.

This is development selection evidence, not unseen accuracy or the full 144-trial model/tool acceptance comparison. The cases are synthetic and agent-authored; there was no human explanation review. Temperature-zero repetitions assess repeatability within this harness and do not establish statistical independence or broad model superiority.

The source hash check records that `provider.py` changed on disk during selection: HTTP error responses gained an explicit socket close. The already-imported provider code stayed fixed inside the selection process, and no HTTP-error trial occurred. The discrepancy is retained as `source_unchanged: false`; this run must not be described as a clean, commit-pinned release evaluation. Later numeric edge-case fixes were also made after selection. The separate final model comparison records the frozen release revision.
