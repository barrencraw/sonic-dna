# Mini Chain Contract: DNA Batch Processing Chain

## Overview
This contract defines the operational parameters, invariants, idempotency guarantees, atomicity boundaries, and telemetry requirements for the DNA Batch Processing chain (`utils/dna_ui.py` & `main.py`).

---

## Contract Specification

### 1. Trigger
- Manual execution via `main.py --once` or `run_batch()`.
- Background watcher loop monitoring `data/raw/toSequence.txt` for new DNA sequences.

### 2. Inputs
- File: `data/raw/toSequence.txt` (UTF-8 encoded text file with one DNA sequence per line).
- Rules: JSON rule files in `rules/` directory (e.g., `rules/rules_Volume.json`).
- Ledger: `data/processed_ledger.json` (JSON store tracking previously processed idempotency keys).

### 3. Terminal States
- `success`: Sequence successfully parsed against rule definitions and appended to dataset outputs.
- `error`: Sequence failed parsing due to invalid syntax or unknown rule prefix (`RuleParseError`); error recorded in ledger and output files.
- `skipped`: Sequence already exists in `processed_ledger.json`; skipped without re-computation or duplicate output entry.

### 4. Invariants
- **Atomicity:** All dataset output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are committed atomically. No torn writes or partial file contents exist on error.
- **Idempotency:** Re-submitting an already processed DNA sequence is a non-mutating operation on the output dataset.
- **Watcher Protection:** `data/raw/toSequence.txt` is cleared if and only if `run_batch()` completes without unhandled errors or persistence failures.

### 5. Error Taxonomy
- `DNAProcessingError`: Base class for all batch processing exceptions.
- `RuleLoadError`: Raised when JSON rules cannot be loaded or initialized from the `rules/` directory.
- `PersistenceError`: Raised when writing temporary files, flushing/syncing disk handles, or renaming output files fails.

### 6. Idempotency Key
- Key: The exact DNA sequence string (e.g., `VOL08900750712`).
- Storage: `data/processed_ledger.json` maps key to `{ terminal_outcome, timestamp }`.

### 7. Atomicity Boundary
- All output files are generated inside a temporary directory (`tempfile.TemporaryDirectory(dir=output_folder)`).
- File streams are flushed (`flush()`) and synced to physical media (`os.fsync()`).
- Atomic replacement (`os.replace()`) moves temporary files to their destination paths.

### 8. Required Logs & Telemetry
- Log format for key evaluations:
  - `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- Log format for batch execution results:
  - `[OK] Processed <count> new DNA strings. Total in ledger: <total>`

---

## Grep Recipes

```bash
# Check idempotency deduplication hits
grep "\[Idempotency\]" data/logs.log | grep "dedupe_hit=True"

# Check processing errors
grep -E "\[ERROR\]|\[CRITICAL\]|RuleParseError" data/logs.log

# Track batch completions
grep "\[OK\] Processed" data/logs.log
```
