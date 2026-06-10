# CONTRACT: DNA Batch Processing Chain

## Trigger
- **Watcher**: `main.py` background thread detecting changes in `data/raw/toSequence.txt`.
- **Manual**: `main.py --once` CLI invocation.

## Inputs
- `data/raw/toSequence.txt`: New DNA strings (one per line).
- `rules/*.json`: Parsing rules.
- `data/ledger.json`: Idempotency ledger (stateful).

## Terminal States
- `SUCCESS`: DNA parsed and recorded in JSON/CSV/Ledger.
- `DEDUPE_SKIP`: DNA already present in ledger; skipped.
- `PARSE_ERROR`: DNA malformed; error recorded in JSON/CSV/Ledger.
- `ATOMIC_FAILURE`: IO error during commit; no files changed.

## Invariants
- **Atomicity**: Either all output files (JSON, CSV, Ledger) are updated, or none are.
- **Idempotency**: Processing the same DNA string multiple times results in exactly one entry in the results.
- **Observability**: Every batch run must have a unique `correlation_id` in logs.

## Error Classes
- `RuleParseError`: Malformed DNA (Handled, non-terminal for batch).
- `PersistenceError`: IO/Atomicity failure (Terminal for batch).
- `ThermalOverloadError`: System too hot (Terminal for batch, if implemented).

## Required Logs
- `JSON_LOG: { "step": "batch_start", "correlation_id": "...", ... }`
- `JSON_LOG: { "step": "item_processed", "outcome": "...", "idempotency_key": "...", ... }`
- `JSON_LOG: { "step": "batch_end", "outcome": "success", ... }`
