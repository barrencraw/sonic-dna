# Chain Contract: DNA Batch Parsing

## Overview
This contract defines the operational parameters, terminal states, invariants, error handling, idempotency rules, atomicity boundaries, and logging requirements for the **DNA Batch Parsing Chain** in SonicDNA.

---

## 1. Trigger
- **File Watcher (`main.py`)**: Automatic trigger when new non-empty content is appended to `data/raw/toSequence.txt`.
- **Once-Runner (`main.py --once`)**: Explicit CLI invocation triggering `process_once()`.
- **Direct Library Invocation**: Explicit invocation of `utils.dna_ui.main()` / `run_batch()`.

---

## 2. Inputs
- **Input Queue File**: `data/raw/toSequence.txt` (contains line-delimited DNA sequences, e.g. `VOL08900750712`).
- **Rule Configurations**: `rules/rules_*.json` (loaded via `DNACalculator`).
- **Idempotency Ledger**: `data/processed_ledger.json`.
- **Existing Outputs**:
  - `data/output/toSequence_parsed.json`
  - `data/output/toSequence_parsed.csv`

---

## 3. Terminal States
Each DNA sequence processed transitions to exactly one terminal state in `data/processed_ledger.json`:
- **`SUCCESS`**: Parsed successfully according to matching rule set and added to output dataset.
- **`ERROR`**: Rule parse failure (e.g. `RuleParseError` due to unknown prefix or malformed values). Recorded in output dataset with error details.
- **`SKIPPED`**: Already exists in `processed_ledger.json` (deduplication hit). Output files are unaffected.
- **`REFUSED`**: Unhandled file/system failure or missing input file / missing rules directory. Operation aborted without mutating existing outputs.

---

## 4. Invariants
1. **No Torn / Partial Writes**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and the ledger (`processed_ledger.json`) MUST be written using temp files and atomic renames (`os.replace`).
2. **Queue Draining Consistency**: The input file (`data/raw/toSequence.txt`) is cleared (`clear_input_file`) ONLY if `run_batch()` completes without unhandled exceptions.
3. **Idempotency Guarantee**: Submitting the same DNA sequence multiple times produces identical output datasets and ledger state without duplicate records.
4. **Data Preservation**: When processing new DNA sequences, pre-existing valid records in JSON/CSV output files are preserved.

---

## 5. Error Taxonomy
- `DNAProcessingError`: Base exception for all DNA processing failures.
  - `RuleLoadError`: Raised when rules directory or rule JSON files cannot be loaded.
  - `PersistenceError`: Raised when temp file writes, syncs, or atomic renames fail.

---

## 6. Idempotency Key
- **Key Definition**: The trimmed DNA sequence string (e.g., `VOL08900750712`).
- **Scope**: Unique per DNA sequence across all batch runs.

---

## 7. Atomicity Boundary
The atomic transaction boundary spans:
1. Load `processed_ledger.json` and existing JSON/CSV outputs.
2. Filter DNA sequences against ledger.
3. Parse new DNA sequences via `DNACalculator`.
4. Stage JSON, CSV, and ledger writes into temporary directory handles.
5. Commit staged files to final destination via `fsync` and `os.replace`.
6. Truncate input file (`toSequence.txt`).

---

## 8. Telemetry & Required Logs
All batch processing runs must emit structured log statements with the following key-value properties:
- `[Idempotency] key=<DNA_STR> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `[OK] Processed <N> new DNA strings. Total in ledger: <TOTAL>`

---

## 9. Telemetry Grep Recipes
- **Find all deduplication hits**:
  ```bash
  grep "dedupe_hit=True" logs.txt
  ```
- **Find all successful parses in telemetry**:
  ```bash
  grep "terminal_outcome=success" logs.txt
  ```
- **Find all parse errors recorded in telemetry**:
  ```bash
  grep "terminal_outcome=error" logs.txt
  ```
