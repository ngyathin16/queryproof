# Architecture and tradeoffs

## Boundaries

The browser submits a UTF-8 CSV bundle, contract and SQL to a loopback-only HTTP service. The server rejects unexpected Host/Origin values and cross-site browser requests. It accepts JSON mutations only, caps request size, serves only built UI files and never accepts filesystem input paths. This prevents a browser page from silently using the local analysis service.

Imports validate table and column identifiers, declared types, row shape, size and row counts. SQLite stores canonical snapshot payloads under their content identity. Review inputs are append-only: each query/contract revision makes a new run linked to its predecessor. Terminal state updates only apply to running records, so a late worker result cannot turn a cancelled review into a completed success. On process startup, unfinished runs become interrupted.

The SQL grammar is an explicit AST allowlist, backed by runtime restrictions. Supported SQL runs inside a disposable worker with no external access or extension loading, a 256 MB DuckDB memory budget, one execution thread and no disk spill. The parent terminates it on cancellation or after ten seconds. Windows uses a 768 MB process Job limit; Linux uses a 768 MB resident-memory watchdog sampled every 100 ms and a CPU limit. Linux memory can briefly overshoot between samples; this is not a hard cgroup ceiling. A virtual-address-space limit caused DuckDB's native allocator to fail during Linux startup and was replaced after reproducing that failure. These restrictions are complementary; parsing alone is not a sandbox.

The reference evaluator uses Python rows and Decimal arithmetic from the declared metric contract. It does not derive expected values by rewriting the reviewed SQL. Join population, date, null and grouped-result checks are distinct. A result cannot pass with a missing required definition or an unsupported check. Complete group comparisons precede display truncation; NULL and absent groups remain distinct.

Relationship declarations default to the metric base table; `source_table` explicitly names another imported table for a chained path. Every join matches a declared key pair and checks the actual source/target cardinality. Stable keys identify base entities, while relationship keys may legitimately repeat; preaggregating a many-to-many branch preserves the declared base grain. Measures and grouping still come from the base table. Ratio denominator witnesses catch wrong intermediate populations even when zero numerators hide the final-value discrepancy.

## Persistence and exports

Snapshots, runs and model trials live in a local SQLite database. The UI marks changed SQL/contract/data as stale and keeps history available. Each run contains its original input even after a revision is reviewed. Reset restores a working draft; it does not destroy previous evidence.

Exports identify the dataset, reviewed SQL, contract, findings, runtime versions and reproduction steps. Example source rows require an explicit export choice. Input CSVs and model conversations are excluded. Reproducing an imported review requires the original local input bundle; a hash cannot reconstruct it.

## Model boundary

Only an explicitly requested assistance run receives contract/schema/SQL and bounded evidence. Local Ollama is the default; an operator can configure an HTTPS OpenAI-compatible provider with a server-side key. The UI discloses the selected endpoint and whether evidence will leave the machine. Keys are never sent to the UI or persisted with reviews, redirects are rejected, and raw provider error bodies are withheld. Tools can inspect the contract/schema, inspect findings and evaluate a revision. They cannot edit a contract, access files, choose a remote host or run unrestricted SQL. Model proposals and numeric claims are validated, and every proposed revision is executed through the deterministic path. Timeouts, malformed output and failed repairs remain failures. Models can still produce misleading prose; the application never treats fluent explanation as verified evidence.

## Scope

This implementation has one local operator, one SQL dialect and application-owned snapshots. It is not a hosted query executor or a universal SQL correctness checker. Some contract forms remain unsupported; see the acceptance map and explicit messages in the application. Unsupported cases must not be counted as verified. Structural evaluation uses independently calculated row-oracle expectations; human review and broader real-world validation remain external follow-up work.
