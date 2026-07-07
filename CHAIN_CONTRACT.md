# DNA Batch Parsing Chain Contract

## Trigger
- Manual execution of `main.py --once`.
- `main.py` watcher detecting new content in `data/raw/toSequence.txt`.

## Inputs
- `data/raw/toSequence.txt`: A file containing one DNA sequence per line.
- `rules/*.json`: Rule definitions for parsing DNA sequences.
- `data/processed_ledger.json`: Idempotency ledger.

## Terminal States (Per Sequence)
- `SUCCESS`: Sequence parsed successfully and results stored.
- `ERROR`: Parsing failed due to invalid DNA or missing rules.
- `SKIPPED`: Sequence already exists in the ledger with a `SUCCESS` outcome.

## Invariants
- **Atomic Multi-File Commit**: Ledger, JSON output, and CSV output are updated as a single logical unit.
- **No Silent Drains**: Input sequences are only considered "processed" if they are successfully committed to the ledger and outputs.
- **Traceability**: Every batch run has a unique `correlation_id`.

## Error Classes
- `RuleLoadError`: Failed to load rule definitions.
- `DNAProcessingError`: General error during batch processing.
- `PersistenceError`: Failed to write output files atomically.

## Idempotency Key
- The raw DNA sequence string.

## Atomicity Boundary
- The `os.replace` calls at the end of the batch process, committing temp files to their final destinations.

## Required Logs
- Structured JSON logs with prefix `JSON_LOG:` containing:
  - `timestamp` (ISO 8601 UTC)
  - `correlation_id`
  - `actor_id`
  - `chain_name` ("dna-batch-parse")
  - `step` (e.g., "start", "sequence-parsed", "commit", "end")
  - `outcome` (e.g., "success", "error", "skipped")

## Grep Recipe for Telemetry
```bash
grep 'JSON_LOG:' | sed 's/JSON_LOG: //' | jq '.'
```
