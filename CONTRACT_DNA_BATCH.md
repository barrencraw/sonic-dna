# Chain Contract: DNA Batch Parsing

## Overview
Processes a batch of DNA strings from a raw input file, generating structured JSON and CSV outputs while maintaining an idempotency ledger to avoid redundant processing.

## Trigger
- **Watcher:** Detects changes in `data/raw/toSequence.txt`.
- **Manual:** `python main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: Plain text file, one DNA string per line.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Existing idempotency state.

## Terminal States
- **SUCCESS:** All new DNA strings parsed and outputs committed.
- **PARTIAL_SUCCESS:** Some strings parsed successfully, others failed `RuleParseError`, but all were recorded and outputs committed.
- **ERROR:** Fatal infrastructure failure (e.g., Disk Full, Permission Denied) prevents atomic commit.
- **NO_NEW_DNA:** No strings found or all strings were already in the ledger.

## Invariants
- **Atomicity:** JSON output, CSV output, and Ledger must be updated together or not at all.
- **Idempotency:** A DNA string is only parsed if its exact string is not already a key in the ledger with a terminal outcome.
- **Durability:** Files are flushed and synced to disk before the atomic rename.

## Telemetry
Logs must be pipe-delimited for easy grepping.

### Grep Recipes
- `grep "| ERROR |"` : Find fatal errors.
- `grep "| COMMIT |"` : Find successful batch completions.
- `grep "VOL08900750712"` : Trace a specific DNA string processing.

### Structured Fields
`| timestamp | level | correlation_id | message |`

## Error Classes
- `RuleLoadError`: Missing or malformed rule files.
- `RuleParseError`: DNA string does not match any rule or is malformed.
- `PersistenceError`: Failed to write outputs or update ledger atomically.
