# Batch DNA Parser Contract

## Trigger
Append one or more DNA strings to `data/raw/toSequence.txt`.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA string per line.
- `rules/*.json`: Rule definition files for various audio properties.
- `data/processed_ledger.json`: Persistence ledger for idempotency.

## Terminal States
- `SUCCESS`: The DNA string was successfully parsed and added to output files.
- `PARSE_ERROR`: The DNA string failed to parse according to the matched rule.
- `SKIPPED`: The DNA string was already present in the ledger and was skipped.

## Invariants
- **Atomic Commit**: Output JSON, CSV, and the Ledger are updated together. If any write fails, none of the files are updated.
- **Idempotency**: Processing the same DNA string multiple times results in only one entry in the final output files.
- **Deduplication**: If a DNA string exists in the ledger, it is not re-processed.
- **Input Preservation**: The input file `toSequence.txt` is only cleared by the caller (`main.py`) if the batch process completes without raising a `DNAProcessingError`.

## Error Classes
- `RuleLoadError`: Failed to load rule JSON files.
- `RuleParseError`: A specific DNA string does not match its rule schema.
- `PersistenceError`: Failed to write output files atomically.
- `DNAProcessingError`: Generic base class for processing failures.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- The `os.replace` calls at the end of `utils.dna_ui.main()`, committing temp files to their final paths.

## Required Logs (Structured JSON)
Logs should include:
- `correlation_id`: Unique ID for the batch run.
- `idempotency_key`: The DNA string being processed.
- `terminal_outcome`: `SUCCESS`, `PARSE_ERROR`, or `SKIPPED`.
- `latency_ms`: Time taken to process the individual string.
- `step`: Current stage (e.g., `start`, `parsing`, `committing`).

## Telemetry Grep Recipes
- **Find failed parses**: `grep "PARSE_ERROR" logs.json`
- **Track batch progress**: `grep "committing" logs.json`
- **Check deduplication**: `grep "SKIPPED" logs.json`
