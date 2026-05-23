# Contract: DNA Batch Processing

## Trigger
- Addition of new DNA strings to `data/raw/toSequence.txt`.
- Manual invocation of `main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: New DNA strings to process (one per line).
- `data/processed_ledger.json`: Record of previously processed DNA strings to ensure idempotency.
- `data/output/toSequence_parsed.json`: Cumulative JSON output.
- `data/output/toSequence_parsed.csv`: Cumulative CSV output.

## Terminal States
- `SUCCESS`: DNA string parsed and added to output.
- `PARSE_ERROR`: DNA string failed validation/parsing; error recorded in output.
- `SKIPPED`: DNA string already present in ledger; processing bypassed.

## Invariants
1. **Atomicity**: The output files (JSON, CSV) and the ledger must be updated together. If any part of the write fails, none of the files should be updated, and the input file should not be cleared.
2. **Idempotency**: A DNA string with a specific content must only be processed once. Subsequent attempts must hit the ledger and be skipped.
3. **Consistency**: The JSON and CSV outputs must contain the same set of processed DNA strings.

## Error Classes
- `RuleLoadError`: Failed to load parsing rules.
- `RuleParseError`: Individual DNA string failed parsing.
- `PersistenceError`: Failed to write output files atomically.
- `DNAProcessingError`: General processing failure.

## Required Logs
- `correlation_id`: Unique ID for the batch run.
- `idempotency_key`: The DNA string being processed.
- `step`: Current stage (e.g., `start`, `parsing`, `committing`).
- `outcome`: Terminal state for the specific key.
