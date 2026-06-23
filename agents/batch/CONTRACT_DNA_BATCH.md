# DNA Batch Processing Chain Contract

## Trigger
- **Watcher:** Background thread in `main.py` monitoring `data/raw/toSequence.txt`.
- **Manual:** Running `python main.py --once`.

## Inputs
- **File:** `data/raw/toSequence.txt` (One DNA string per line).
- **Parameters:** `correlation_id` (UUID), `actor_id` (e.g., "dna_watcher", "once_runner").

## Terminal States
- **success:** DNA string parsed and appended to JSON/CSV output.
- **error:** DNA string failed to parse (logged with error message).
- **skipped:** DNA string already exists in the ledger.

## Invariants
- **Idempotency:** A DNA string is never processed twice if it exists in `data/processed_ledger.json`.
- **Atomicity:** All output files (`.json`, `.csv`, `_ledger.json`) are updated together using an atomic write-and-rename pattern. If any write fails, none of the files are updated.
- **Traceability:** Every batch run generates a unique `correlation_id` propagated through all logs.

## Error Classes
- `RuleLoadError`: Failed to load JSON rules.
- `DNAProcessingError`: General error reading input or processing batch.
- `PersistenceError`: Failure during atomic write or file rename.

## Required Logs
- `JSON_LOG:` prefixed entries for:
  - `batch_start`
  - `dna_parse` (per item, including `idempotency_key` and `latency_ms`)
  - `atomic_write` (on error)
  - `batch_end`
