# Contract: DNA Batch Parser

## Trigger
- File watcher detects changes in `data/raw/toSequence.txt`.
- Manual invocation via `main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: Text file with one DNA string per line.
- `rules/*.json`: Rule definitions for the `DNACalculator`.

## Terminal States
- `SUCCESS`: DNA string parsed and appended to output.
- `PARSE_ERROR`: DNA string failed validation/parsing; error recorded in output.
- `SKIPPED`: DNA string already exists in `processed_ledger.json`.

## Invariants
- **Atomic Commit**: JSON output, CSV output, and the processed ledger must be updated together. If any write fails, none of the files should reflect a partial update.
- **Idempotency**: Processing the same DNA string multiple times must not result in duplicate entries in the output files.
- **Drainage**: `toSequence.txt` must only be cleared if the batch processing and atomic commit succeed.

## Error Classes
- `RuleLoadError`: Failed to load JSON rules.
- `DNAProcessingError`: General failure during the processing loop.
- `PersistenceError`: Failed to write or rename output files.
- `RuleParseError`: Specific DNA string does not match any rule.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- The "Commit" phase where temporary files are renamed to:
    - `data/output/toSequence_parsed.json`
    - `data/output/toSequence_parsed.csv`
    - `data/processed_ledger.json`

## Required Logs
- `idempotency_key`
- `dedupe_hit` (boolean)
- `terminal_outcome` (`success`, `error: <msg>`, or `skipped`)
- `latency_ms` (per-batch or per-string)

## Telemetry Grep Recipes
- **Find all failed DNA parses**:
  `grep '"step": "parse_sequence"' logs.json | grep -v '"outcome": "success"'`
- **Calculate average batch latency**:
  `grep '"step": "batch_commit"' logs.json | awk -F'"latency_ms": ' '{print $2}' | sed 's/}.*//' | awk '{sum+=$1; count++} END {print sum/count}'`
- **Check for deduplication hits**:
  `grep '"dedupe_hit": true' logs.json`
