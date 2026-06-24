# Contract: DNA Batch Processing Chain

## Trigger
- **Watcher**: `main.py` detects new content in `data/raw/toSequence.txt`.
- **Manual**: `python main.py --once` is executed.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA string per line.
- `rules/*.json`: Rule definitions for parsing DNA strings.

## Terminal States
- `SUCCESS`: DNA string parsed and recorded in JSON/CSV outputs.
- `ERROR`: DNA string failed validation or parsing; error recorded in JSON/CSV outputs.
- `SKIPPED`: DNA string already present in `processed_ledger.json` (idempotency hit).

## Invariants
- **Atomicity**: Either all outputs (JSON, CSV, Ledger) are updated, or none are. No torn writes.
- **Idempotency**: Processing the same DNA string multiple times results in the same state without duplicate output entries.
- **Traceability**: Every processing step is logged with a `correlation_id` and `actor_id`.

## Error Classes
- `RuleLoadError`: Rules folder or files are missing or malformed.
- `RuleParseError`: Individual DNA string does not match any rule.
- `PersistenceError`: Failure during the atomic write phase.
- `DNAProcessingError`: Generic catch-all for batch failures.

## Idempotency Key
- The raw DNA string itself is used as the uniqueness key in `data/processed_ledger.json`.

## Atomicity Boundary
- The final `os.replace` calls for the Ledger, JSON, and CSV files within the `utils.dna_ui.main` function.

## Required Logs
- Format: `JSON_LOG: { "timestamp": ..., "correlation_id": ..., "step": ..., "outcome": ..., ... }`
- Steps: `batch_start`, `item_process`, `atomic_write_start`, `atomic_write_complete`, `batch_end`.
