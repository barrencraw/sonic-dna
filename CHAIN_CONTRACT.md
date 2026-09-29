# DNA Batch Parsing Chain Contract

## Overview
This document specifies the mini Chain Contract for the DNA Batch Parsing pipeline.

## Contract Specification

- **Trigger**:
  - File update in `data/raw/toSequence.txt` detected by watcher in `main.py` OR manual execution via `--once` flag.

- **Inputs**:
  - Raw DNA sequences from `data/raw/toSequence.txt` (one string per line).
  - Existing execution ledger from `data/processed_ledger.json`.

- **Terminal States**:
  - `success`: DNA sequence parsed and appended to JSON and CSV outputs.
  - `error`: Rule parsing error captured, logged, and appended as error entry in outputs.
  - `skipped`: Duplicate sequence skipped due to ledger match (idempotency key hit).

- **Invariants**:
  - **No Partial/Torn Writes**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) are written atomically via temp files, flush, fsync, and replace operations.
  - **Deduplication**: Input DNA sequences present in `data/processed_ledger.json` are skipped and never re-processed or duplicated in output files.
  - **Input Retention on Failure**: `toSequence.txt` is only cleared when batch parsing completes successfully. On failure, input is retained for retries.

- **Error Classes**:
  - `DNAProcessingError`: Base exception class for DNA batch processing errors.
  - `RuleLoadError`: Raised when rules cannot be loaded from the rules folder.
  - `InputReadError`: Raised when `toSequence.txt` cannot be read.
  - `PersistenceError`: Raised when atomic file operations or writes fail.
  - `RuleParseError`: Raised when a specific DNA sequence fails rule parsing.

- **Idempotency Key**:
  - The raw DNA sequence string (e.g., `VOL08900750712`).

- **Atomicity Boundary**:
  - All outputs (`toSequence_parsed.json` and `toSequence_parsed.csv`) and the ledger (`processed_ledger.json`) are updated together in a single atomic commit step.

- **Required Logs**:
  - Deduplication logs: `[Idempotency] key=<DNA_KEY> dedupe_hit=<True|False> terminal_outcome=<OUTCOME>`
  - Processing summary: `[OK] Processed <COUNT> new DNA strings. Total in ledger: <TOTAL>`

- **Grep Recipe**:
  - Filter idempotency events: `grep "\[Idempotency\]" logs.txt`
  - Filter deduplication hits: `grep "dedupe_hit=True" logs.txt`
  - Filter critical errors: `grep "\[CRITICAL\]" logs.txt`
