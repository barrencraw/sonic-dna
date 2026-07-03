# DNA Batch Parsing Chain Contract

## Trigger
- Watcher detects new non-empty content in `data/raw/toSequence.txt`.
- Manual invocation via `python main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.
- `rules/*.json`: Rule definitions for parsing.

## Terminal States
- `SUCCESS`: DNA parsed correctly and recorded.
- `ERROR`: DNA failed to parse due to `RuleParseError`.
- `SKIPPED`: DNA already exists in ledger and was previously successfully processed or errored.
- `REFUSED`: Processing refused (e.g. thermal lockout - planned).

## Invariants
- **Atomic Commits**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and the `processed_ledger.json` are updated using a temporary directory and atomic rename to ensure consistency.
- **No Silent Drains**: The input file `toSequence.txt` is only cleared if the processing run completes without unhandled exceptions.
- **Idempotency**: Identical DNA strings are not re-parsed if they already exist in the ledger.

## Error Classes
- `DNAProcessingError`: Base class for chain failures.
- `RuleLoadError`: Failed to load JSON rules from disk.
- `RuleParseError`: DNA string does not conform to any loaded rule.
- `PersistenceError`: Failed to write output files atomically.

## Idempotency Key
- The raw DNA sequence string.

## Atomicity Boundary
- The `dna_ui.main` function encompasses the atomicity boundary for a batch.

## Required Logs
- Structured logs prefixed with `JSON_LOG:` containing:
  - `correlation_id`: Unique ID for the batch run.
  - `step`: `batch_start`, `item_check`, `item_parsed`, `batch_commit`, `batch_end`.
  - `outcome`: `success`, `error`, `skipped`.
  - `dna_sequence`: The sequence being processed.

## Telemetry Analysis
- Grep recipe: `grep "JSON_LOG:" | sed 's/JSON_LOG: //' | jq '.'`
- Analysis command (if logging to file): `grep "JSON_LOG:" data/output/processing.log | sed 's/JSON_LOG: //' | jq '.'`
