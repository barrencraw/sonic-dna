# SonicDNA Chain Contract: DNA Batch Parsing

## Overview
This document specifies the formal contract for the **DNA Batch Parsing** processing chain (`utils/dna_ui.py` & `main.py`).

---

## Contract Specification

### 1. Trigger
- Background file watcher (`main.py`) detecting changes in `data/raw/toSequence.txt`.
- One-off CLI execution via `python main.py --once`.
- Programmatic invocations of `utils.dna_ui.run_batch(correlation_id=..., actor_id=...)`.

### 2. Inputs
- `toSequence.txt`: UTF-8 encoded text file containing one raw DNA sequence string per line (e.g., `VOL08900750712`).
- `correlation_id`: Optional tracing UUID string.
- `actor_id`: Optional actor identifier string (defaults to `batch_parser`).

### 3. Terminal States
The terminal status for each processed DNA sequence is defined by `DNAStatus`:
- `success`: DNA sequence parsed validly against defined rules and stored in output datasets.
- `error`: DNA sequence failed parsing (e.g. `RuleParseError`), stored with error details.
- `skipped`: DNA sequence previously processed and stored in ledger (idempotent deduplication hit).
- `refused`: Batch execution halted or rejected due to system lockout or critical persistence failure.

### 4. Invariants
- **Idempotency**: Repetitive execution with identical inputs produces zero duplicate entries in output datasets (`JSON`/`CSV`) and performs no redundant disk writes when `new_processed_count == 0`.
- **Atomicity**: Output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) are written to a temporary directory in the target volume, flushed, fsynced to physical disk, and atomically swapped using `os.replace`.
- **Queue Preservation**: The raw queue `data/raw/toSequence.txt` is truncated by `main.py` only after `run_batch()` completes without throwing unhandled exceptions.
- **Backward Compatibility**: JSON/CSV rows preserve both legacy (`dna`) and canonical (`dna_sequence`) keys. Ledger reads support both structured (`{'ledger': {...}}`) and flat dictionary formats.

### 5. Error Taxonomy
Inheritance hierarchy for DNA batch processing exceptions:
```
DNAProcessingError (Exception)
├── InputReadError
├── RuleLoadError
└── PersistenceError
    ├── LedgerLoadError
    ├── LedgerSaveError
    └── AtomicWriteError
```

### 6. Idempotency Key Strategy
- **Key Formulation**: Trimmed raw DNA sequence string (`dna_sequence`).
- **Ledger Path**: `data/processed_ledger.json`.
- **Deduplication Logic**: Any sequence existing in the ledger with a terminal outcome (`success`, `error`, `skipped`, `refused`) is skipped.

### 7. Atomicity Boundary
1. Create temporary directory under `data/output/`.
2. Write parsed JSON and CSV to temporary files within the directory.
3. Call `.flush()` and `os.fsync(fd)` on temporary file handles.
4. Execute `os.replace(tmp_file, target_file)` for atomic replacement.
5. Save updated ledger to `data/processed_ledger.json`.

### 8. Required Telemetry
Structured logs are emitted to `stdout` with the `JSON_LOG:` prefix and contain the following mandatory JSON fields:
- `timestamp`: UTC ISO 8601 string (e.g., `2025-06-02T12:00:00Z`).
- `correlation_id`: Trace correlation UUID string.
- `actor_id`: Actor identity (e.g., `batch_parser`).
- `chain_name`: `"dna_batch_parsing"`.
- `step`: Process phase (`"start"`, `"parse"`, `"dedupe"`, `"write_output"`, `"save_ledger"`, `"end"`).
- `outcome`: Lowercase `DNAStatus` enum value (`"success"`, `"error"`, `"skipped"`, `"refused"`).
- `latency_ms`: Duration in milliseconds.
- `idempotency_key`: DNA sequence string (or `null` for batch-level logs).
- `outcome_detail`: Detailed string or dict context.

---

## Grep Recipes

### Filter all structured JSON logs:
```bash
grep "JSON_LOG:" log_file.log
```

### Trace a specific batch execution by correlation ID:
```bash
grep "JSON_LOG:" log_file.log | grep '"correlation_id": "<YOUR_CORRELATION_ID>"'
```

### Summary of terminal outcomes across batch runs:
```bash
grep "JSON_LOG:" log_file.log | grep '"step": "end"'
```
