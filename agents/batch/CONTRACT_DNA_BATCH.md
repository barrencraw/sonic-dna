# Contract: DNA Batch Parsing Chain

## Overview
This chain processes a batch of DNA sequences from a raw text file, calculates their sonic properties using systemic rules, and updates cumulative JSON and CSV datasets.

## Chain Details
- **Trigger**:
    - `main.py` watcher detects changes in `data/raw/toSequence.txt`.
    - CLI invocation: `python3 main.py --once`.
- **Inputs**:
    - `data/raw/toSequence.txt` (One DNA sequence per line).
    - `rules/*.json` (Systemic rule definitions).
- **Terminal States**:
    - `SUCCESS`: All sequences processed or skipped (if already in ledger), outputs committed.
    - `PARSE_ERROR`: Individual sequence failed validation/parsing (recorded in outputs as error).
    - `FATAL_ERROR`: Infrastructure failure (I/O, disk full, missing rules) preventing commit.
- **Invariants**:
    - **Idempotency**: A `DNASequence` is never processed twice if it exists in the ledger.
    - **Atomicity**: The JSON output, CSV output, and Idempotency Ledger are committed as a single unit.
    - **Sync**: The raw input file is only truncated after a successful atomic commit.
    - **Consistency**: JSON and CSV files always contain the same set of processed sequences.

## Idempotency & Persistence
- **Idempotency Key**: `DNASequence` (the raw string).
- **Ledger**: `data/processed_ledger.json`.
- **Atomic Boundary**:
    1. Write JSON, CSV, and Ledger to `data/output/.tmp/`.
    2. Atomic `os.replace` to final destinations.

## Error Classes
- `RuleLoadError`: Failed to initialize the `DNACalculator` or load rules.
- `DNAProcessingError`: Catch-all for sequence-level issues.
- `PersistenceError`: Failed to write or commit output files.

## Telemetry Requirements
- **Structured Logs**:
    - `idempotency_key`: The DNA string being processed.
    - `dedupe_hit`: Boolean, true if sequence was skipped.
    - `terminal_outcome`: `success`, `error: <msg>`, or `skipped`.
    - `step`: `start` or `end`.
- **Telemetry Grep Recipes**:
    - *Find dedupe hits*: `grep "dedupe_hit=True"`
    - *Find parse errors*: `grep "terminal_outcome=error"`
    - *Track sequence lifecycle*: `grep "key=DNA_STRING"`
