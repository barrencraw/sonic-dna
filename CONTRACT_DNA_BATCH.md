# CONTRACT_DNA_BATCH.md

## Trigger
- Manual execution via `python3 main.py --once`
- Background watcher detecting changes in `data/raw/toSequence.txt`

## Inputs
- `data/raw/toSequence.txt`: Newline-separated DNA strings.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Idempotency record of previously processed DNA.

## Terminal States
- `SUCCESS`: DNA string parsed and added to outputs.
- `ERROR`: DNA string failed to parse.
- `DEDUPE`: DNA string already present in ledger; skipped.
- `NO_NEW_DATA`: Input file was empty or contained only duplicates.

## Invariants
- **Atomicity**: JSON output, CSV output, and the processed ledger must be committed together. If any write fails, none of the files should reflect the partial batch.
- **Idempotency**: Processing the same DNA string multiple times must not result in duplicate entries in JSON/CSV.
- **Durable Ledger**: The ledger must be updated only after (or alongside) the data files are successfully written.
- **Input Draining**: `toSequence.txt` must only be cleared if the persistence of results succeeds.

## Error Classes
- `RuleLoadError`: Failed to load or parse rule JSONs.
- `RuleParseError`: Individual DNA string fails validation against its rule.
- `PersistenceError`: Failed to write outputs or update the ledger.
- `DNAProcessingError`: Catch-all for batch-level failures.

## Required Logs (Prefix: [OBSERVABILITY])
- `step=batch_start`: At the beginning of processing.
- `step=process_dna`: For each DNA string (includes `outcome` and `idempotency_key`).
- `step=batch_end`: At the end of processing (includes `total_processed`, `total_errors`).
- Fields: `correlation_id`, `actor_id`, `step`, `outcome`, `idempotency_key`, `latency_ms`.

## Telemetry Triage (Grep Recipe)
- `grep "\[OBSERVABILITY\]" output.log`
- `grep -E "\[OBSERVABILITY\]|\[Idempotency\]" output.log`
