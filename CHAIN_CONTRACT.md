# DNA Batch Processing Chain Contract

## Trigger
- New content detected in `data/raw/toSequence.txt` by the watcher loop in `main.py`.
- Manual execution via `python3 main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA sequence per line.
- `rules/*.json`: Rule definition files for the `DNACalculator`.
- `data/processed_ledger.json`: The idempotency ledger.

## Terminal States
- `SUCCESS`: Sequence parsed and added to output.
- `ERROR`: Parsing failed; error details recorded in output.
- `SKIPPED`: Sequence already present in the ledger; processing bypassed.

## Invariants
- **No Silent Drains**: `toSequence.txt` is only cleared if the batch processing completes successfully.
- **Atomic Multi-File Commit**: JSON output, CSV output, and the Ledger are updated as a single atomic unit.
- **Idempotency**: Identical DNA sequences are not processed more than once.

## Error Classes
- `RuleLoadError`: Failed to load rule definitions.
- `DNAProcessingError`: General failure during sequence reading or processing.
- `PersistenceError`: Failure during the atomic write/commit phase.
- `RuleParseError`: Malformed DNA sequence (handled per-sequence).

## Telemetry
All logs are prefixed with `JSON_LOG: ` and include:
- `timestamp`: ISO 8601 UTC.
- `correlation_id`: Unique ID for the batch run.
- `step`: Current step (`batch_start`, `sequence_process`, `batch_commit`, `batch_complete`, etc.).
- `outcome`: Outcome of the step (`success`, `error`, `skipped`).

### Grep Recipe
To analyze batch outcomes:
```bash
grep 'JSON_LOG:' | sed 's/JSON_LOG: //' | jq '.'
```
To filter by correlation ID:
```bash
grep 'JSON_LOG:.*"correlation_id": "YOUR_ID"'
```
