# DNA Batch Parsing Chain Contract

## Trigger
- `main.py` watcher detects changes in `data/raw/toSequence.txt`.
- `main.py --once` is executed manually.

## Inputs
- `data/raw/toSequence.txt`: List of DNA strings to process.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Persistence for idempotency.
- `data/output/toSequence_parsed.json/csv`: Existing cumulative outputs.

## Terminal States
- `SUCCESS`: All new DNA strings processed successfully.
- `ERROR`: A fatal error occurred during the batch (e.g., rule loading failed).
- `SKIPPED`: All DNA strings in the input were already in the ledger.
- `NO_NEW_DNA`: Input file was empty or only contained whitespace.
- `PARTIAL_SUCCESS`: Some DNA strings succeeded, others failed parsing, but the batch completed.

## Invariants
- `toSequence.txt` is only truncated by the caller (`main.py`) if the batch processor completes without a fatal exception.
- JSON and CSV outputs must remain in sync (same number of entries, same DNA strings).
- Results are only appended to cumulative files if the DNA string is NOT in the ledger.

## Error Classes
- `RuleLoadError`: Rules folder missing or corrupted.
- `RuleParseError`: DNA string does not match any rule or has invalid format.
- `PersistenceError`: IO failure during atomic write/rename.
- `DNAProcessingError`: Base class for other errors.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- All output writes (JSON, CSV, Ledger) are staged in a `tempfile.TemporaryDirectory` and committed via `os.replace`.

## Required Logs (Structured Telemetry)
Standard format: `ISO8601 | correlation_id | chain_name | step | outcome | latency_ms | actor_id | idempotency_key | [error_message]`

### Grep Recipes
- `| ERROR |` : Find all failed batches or individual parse errors.
- `| COMMIT |` : Find successful atomic commits.
- `VOL08900750712` : Track a specific DNA string through the system.
