# Contract: DNA Batch Processing Chain

## Trigger
- Detection of new, non-empty content in `data/raw/toSequence.txt`.
- Manual invocation via `main.py --once`.

## Inputs
- `dna_sequences`: A list of stripped, non-empty DNA strings from the input file.

## Terminal States (Enum: TerminalOutcome)
- `SUCCESS`: Sequence parsed successfully; results appended to JSON and CSV.
- `PARSE_ERROR`: Sequence failed validation; error recorded in JSON and CSV.
- `SKIPPED`: Sequence already exists in `processed_ledger.json` (Idempotency).

## Invariants
- **Atomic Commits**: JSON, CSV, and Ledger updates must be committed as a single unit or not at all.
- **Idempotency**: A single `dna_sequence` string is processed exactly once unless the ledger is cleared.
- **Sync**: Every entry in the JSON output must have a corresponding row in the CSV output.

## Atomicity Boundary
- The batch process uses a temporary directory for output generation.
- The `os.replace` operation commits the files to the `data/output/` directory.
- The ledger is updated only if the file writes succeed.

## Required Logs (Structured)
- `correlation_id`: UUID for the batch run.
- `step`: `batch_start`, `sequence_start`, `sequence_end`, `batch_end`.
- `outcome`: One of the `TerminalOutcome` values or `error`.
- `latency_ms`: Time taken for the step.

## Telemetry Grep Recipes

### Find failed parses
```bash
grep "PARSE_ERROR" data/processed_ledger.json
# Or via structured logs:
grep '"outcome": "PARSE_ERROR"' logs/batch.log
```

### Track batch progress
```bash
grep -E "batch_start|batch_end" logs/batch.log
```

### Check deduplication hits
```bash
grep '"outcome": "SKIPPED"' logs/batch.log
```

### Trace a specific batch by Correlation ID
```bash
grep "YOUR-UUID-HERE" logs/batch.log
```
