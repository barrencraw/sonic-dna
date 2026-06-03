# DNA Batch Parsing Contract

## Overview
This contract defines the behavior and guarantees of the DNA Batch Parsing chain, which transforms raw DNA sequences into structured JSON and CSV datasets.

## Trigger
- Manual execution of `utils/dna_ui.py`.
- Background watcher in `main.py` detecting changes in `data/raw/toSequence.txt`.
- CLI execution via `main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: A newline-delimited list of DNA strings.
- `rules/*.json`: Rule definition files for parsing DNA components.
- `data/processed_ledger.json`: Persistence layer for tracking processed items.

## Terminal States
- **SUCCESS**: All new DNA strings parsed and appended to JSON/CSV outputs; ledger updated; input file cleared (if handled by caller).
- **DEDUPE_SKIP**: DNA string already exists in the ledger; skipped to prevent redundant computation/duplication.
- **PARSE_ERROR**: Individual DNA string failed validation/parsing; error recorded in outputs; ledger updated to prevent retry of malformed data.
- **ATOMIC_FAILURE**: Critical error during persistence (I/O, Disk Full); no files are partially updated; system rolls back to previous state.

## Invariants
- **Atomicity**: Either JSON, CSV, and Ledger are all updated successfully, or none are.
- **Idempotency**: Processing the same DNA string multiple times results in exactly one entry in the outputs.
- **Data Integrity**: Output files must always be valid JSON/CSV, even if the process is interrupted.

## Error Classes
- `RuleLoadError`: Failed to load or parse JSON rules.
- `DNAProcessingError`: Generic base for processing failures.
- `PersistenceError`: Failed to write outputs or update the ledger atomically.

## Required Logs (Structured)
- `step`: `start`, `dedupe`, `parse`, `commit`, `end`.
- `outcome`: `success`, `skipped`, `error`, `failed`.
- `idempotency_key`: The raw DNA string.
- `correlation_id`: Unique ID for the batch run.
