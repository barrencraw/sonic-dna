# Mini Chain Contract: DNA Batch Parsing

## Overview
This contract governs the **DNA Batch Parsing** chain (`main.py` watcher/runner and `utils/dna_ui.py`).

## Contract Specifications

### 1. Trigger
- Automated file watcher loop in `main.py` detecting non-empty `data/raw/toSequence.txt`.
- Manual/CLI execution via `main.py --once` or direct `run_batch()` function call.

### 2. Inputs
- Input file: `data/raw/toSequence.txt` containing raw DNA sequences (one per line).
- Optional `correlation_id` for end-to-end tracing across batch invocations.

### 3. Terminal States
- **SUCCESS**: All new DNA sequences were parsed and atomically persisted to JSON, CSV, and processed ledger.
- **SKIPPED**: All provided DNA sequences were already recorded in the ledger (no new output generated).
- **ERROR**: Processing or persistence failed with a typed `DNAProcessingError` (`RuleLoadError`, `PersistenceError`). Input file is preserved without clearing.

### 4. Invariants
- **Atomic Persistence**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are written atomically using a temporary directory write-sync-rename (`os.replace`) strategy.
- **Safe Drain**: The input file `toSequence.txt` is cleared ONLY after batch processing and atomic persistence succeed.
- **Idempotent Storage**: Duplicate DNA sequences are recognized via `processed_ledger.json` and will not produce duplicate records in output files.

### 5. Error Taxonomy
- `DNAProcessingError`: Base exception class for all DNA batch processing failures.
  - `RuleLoadError`: Raised when loading JSON rule definitions fails.
  - `PersistenceError`: Raised when writing temporary files or committing via atomic rename fails.
- `RuleParseError`: Raised when individual DNA string parsing fails against defined rules.

### 6. Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

### 7. Atomicity Boundary
- Temporary directory under `data/output/` where output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are flushed and synced before committing via `os.replace`.

### 8. Required Logs & Telemetry
- `[DNA_BATCH_START]`: Emitted at batch start with `correlation_id` and line count.
- `[DNA_PARSE_STEP]`: Emitted per sequence with `correlation_id`, `idempotency_key`, `dedupe_hit`, and `terminal_outcome`.
- `[DNA_BATCH_END]`: Emitted at batch end with `correlation_id`, `processed_count`, and `total_ledger`.

## Grep Recipes
```bash
# Search for batch start events:
grep "DNA_BATCH_START" app.log

# Check for idempotency deduplication hits:
grep "dedupe_hit=True" app.log

# Trace a specific correlation ID across logs:
grep "correlation_id=abc-123" app.log
```
