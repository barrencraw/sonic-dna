# Chain Contract: DNA Batch Parsing

## Overview
This contract defines the requirements for the DNA Batch Parsing engineering loop, ensuring correctness, leverage, and maintainability.

## Win Condition
DNA Batch Parsing is atomic, idempotent, and observable.

## Done When
- [x] Batch processing logic is idempotent (uses a ledger to avoid redundant work).
- [x] Batch processing implements an atomic commit pattern (writes all outputs and ledger to a temporary directory before renaming them).
- [x] Standardized pipe-delimited telemetry is implemented for all major events.
- [x] In-batch deduplication is handled to prevent redundant processing of duplicate DNA strings in a single batch.
- [x] All relevant tests (atomicity, idempotency, regressions) pass.

## Trigger
- Watcher in `main.py` detecting new content in `data/raw/toSequence.txt`.
- Manual execution of `main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA string per line.
- `rules/*.json`: Rule definition files.

## Terminal States
- `SUCCESS`: All new DNA strings processed and committed.
- `ERROR`: A critical failure occurred during processing or persistence.
- `SKIPPED`: DNA string was already in the ledger.

## Invariants
- `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` are always updated as a single atomic transaction.
- Duplicate DNA strings in the same or different batches do not result in duplicate side effects.

## Error Classes
- `RuleLoadError`: Failure to load rule files.
- `DNAProcessingError`: General processing failure.
- `PersistenceError`: Failure to commit output files atomically.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- The writing and renaming of JSON, CSV, and Ledger files in `utils/dna_ui.py`.

## Required Logs (Telemetry)
- `[Batch Start]`
- `[Idempotency]` (per string)
- `[Terminal Outcome]`
- `Persistence failure` (if applicable)
- `Rule load failure` (if applicable)

## Grep Recipe
Use the following command to extract and analyze batch processing telemetry:
`grep "| TELEMETRY |" <log_file> | jq '.data'`
