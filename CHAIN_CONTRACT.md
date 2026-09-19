# Chain Contract: DNA Batch Parsing

## Overview
The DNA Batch Parsing chain processes structured DNA strings from `data/raw/toSequence.txt`, parses their audio variables according to rule definitions, records deduplication state in `data/processed_ledger.json`, and outputs results atomically to `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`.

---

## Contract Specification

### 1. Trigger
- **Watcher (`main.py`)**: Automatic background detection of non-empty `data/raw/toSequence.txt`.
- **Once-Runner (`main.py --once`)**: Manual single-shot command line invocation.
- **Direct API (`utils/dna_ui.py:main()`)**: Python module entry point.

### 2. Inputs
- `data/raw/toSequence.txt`: Text file containing stripped, non-empty DNA strings (one per line).
- `rules/rules_*.json`: Rule definition files for DNA prefix decoding.
- `data/processed_ledger.json`: Existing ledger mapping DNA idempotency keys to terminal outcomes and timestamps.

### 3. Terminal States
- **`SUCCESS`**: All DNA strings evaluated; new results committed atomically to JSON/CSV output and ledger; input file truncated by caller (`main.py`).
- **`ERROR`**: Exception raised during rule loading, input reading, or atomic file persistence; outputs remain untouched; input file (`toSequence.txt`) preserved for safe retries.

### 4. Invariants
1. **Atomicity**: Output JSON, output CSV, and processed ledger are committed together within a single atomic directory swap (`fsync` + `os.replace`). No partial or torn file writes occur.
2. **Idempotency**: DNA strings already present in `processed_ledger.json` are skipped (`dedupe_hit=True`); no duplicate records are appended to cumulative outputs.
3. **Queue Preservation**: `data/raw/toSequence.txt` is cleared IF AND ONLY IF `run_batch()` completes without exception.

### 5. Error Taxonomy
- `DNAProcessingError` (Base Class): Generic error during DNA batch execution.
- `RuleLoadError` (`DNAProcessingError`): Raised when rule definitions cannot be initialized from `rules/`.
- `PersistenceError` (`DNAProcessingError`): Raised when atomic staging, flushing, or renaming of output files/ledger fails.

### 6. Idempotency Key Strategy
- **Key Definition**: The stripped DNA string itself (e.g. `VOL08900750712`).
- **Scope**: Global across batch runs via `data/processed_ledger.json`.

### 7. Atomicity Boundary
- Staging directory: `data/output/.tmp_*`
- Files included in atomic commit:
  - `data/output/toSequence_parsed.json`
  - `data/output/toSequence_parsed.csv`
  - `data/processed_ledger.json`

### 8. Required Telemetry & Logs
Every batch run emits structured console telemetry:
- `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `[OK] Processed <count> new DNA strings. Total in ledger: <total>`
- `[Watcher][CRITICAL] DNA processing failed: <error>` (on exception)

---

## Grep Recipes

- **Trace Idempotency Hits**:
  ```bash
  grep "dedupe_hit=True" app.log
  ```

- **Trace Unprocessed DNA Entries**:
  ```bash
  grep "dedupe_hit=False" app.log
  ```

- **Filter Critical Persistence & Processing Errors**:
  ```bash
  grep -E "\[CRITICAL\]|PersistenceError|RuleLoadError" app.log
  ```

- **Verify Successful Batch Commits**:
  ```bash
  grep "\[OK\] Processed" app.log
  ```
