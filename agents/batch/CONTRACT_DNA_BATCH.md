# DNA Batch Chain Contract

## Overview
The DNA Batch Chain is responsible for processing a batch of DNA strings, converting them into structured JSON and CSV formats, and maintaining an idempotent ledger of processed sequences.

## Trigger
- **Watcher (`main.py`)**: Detects new content in `data/raw/toSequence.txt`.
- **Manual (`main.py --once`)**: Processes all DNA strings in `data/raw/toSequence.txt` once.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA string per line.
- `rules/*.json`: Rule definitions for parsing various DNA properties.
- `data/processed_ledger.json`: Persistent ledger of previously processed DNA strings.

## Terminal States (TerminalOutcome)
- **SUCCESS**: DNA string was successfully parsed and appended to outputs.
- **PARSE_ERROR**: DNA string failed validation or parsing; error recorded in outputs.
- **SKIPPED**: DNA string was already present in the ledger and was not re-processed.

## Invariants
- No DNA string is processed twice (Idempotency).
- JSON, CSV, and Ledger updates are committed together or not at all (Atomicity).
- Numeric leaf values are scaled by Thermal Noise (0.9) if system heat thresholds are exceeded (Future).

## Error Classes
- `RuleLoadError`: Critical failure to load rule definitions.
- `DNAProcessingError`: General error during reading or processing.
- `PersistenceError`: Failure to write output files atomically.
- `DataIntegrityError`: Existing output files are corrupted or unreadable.

## Idempotency Key
- The DNA string itself is the unique identifier for a sequence.

## Atomicity Boundary
- All output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and the `processed_ledger.json` must be updated using an atomic write pattern (temp file + rename).

## Required Logs
- `correlation_id`: Unique trace ID for the batch run.
- `idempotency_key`: The DNA string.
- `step`: `batch_check` or `batch_process`.
- `outcome`: Terminal state or `STARTED`.
