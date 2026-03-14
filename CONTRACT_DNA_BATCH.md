# DNA Batch Chain Contract

## Trigger
- File System: New non-empty lines appended to `data/raw/toSequence.txt` (detected by `main.py` watcher).
- CLI: Execution of `python main.py --once`.

## Inputs
- `correlation_id` (UUID): Unique identifier for the batch execution context.
- `actor_id` (string): 'system' (for watcher) or 'user_batch' (for once-runner).

## Terminal States (Per DNA String)
- `SUCCESS`: DNA parsed successfully and output recorded.
- `ERROR`: Parsing failed (e.g., `RuleParseError`).
- `DEDUPE`: DNA already exists in the `processed_ledger.json`.

## Terminal States (Batch Level)
- `SUCCESS`: Batch completed with at least one new DNA processed.
- `NO_NEW_DATA`: All strings in the batch were deduplicated or input was empty.
- `ERROR`: Critical failure (e.g., `PersistenceError`, `RuleLoadError`).

## Invariants
- **Per-String Idempotency**: Every unique DNA string processed must be recorded in the `processed_ledger.json`. Subsequent attempts to process the same string must result in a `DEDUPE` state.
- **Atomic Persistence**: JSON output, CSV output, and the Ledger must be updated consistently. If any write fails, none of the files should be corrupted or partially updated (implemented via staging and `os.replace`).
- **Input Cleanup**: `toSequence.txt` is only cleared if the batch processing succeeds.

## Required Logs
All logs must use the `[OBSERVABILITY]` prefix and ISO8601 UTC timestamps.

### Start Log
- `step`: "start"
- Fields: `correlation_id`, `actor_id`

### Step Transitions
- `step`: "process_dna"
- Fields: `idempotency_key` (raw DNA), `outcome`

### Completion Log
- `step`: "complete"
- Fields: `outcome` (Batch level), `latency_ms`
