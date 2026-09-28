# Mini Chain Contract: DNA Batch Parsing Chain

## Overview
The DNA Batch Parsing chain is responsible for reading raw DNA strings from `data/raw/toSequence.txt`, validating and parsing them via rule definitions, appending the structured results to output stores (`data/output/toSequence_parsed.json` and `.csv`), and maintaining an execution ledger (`data/processed_ledger.json`).

---

## Contract Specification

### 1. Trigger
- **File System / Manual**: Non-empty `data/raw/toSequence.txt` detected by `main.py` watcher loop or triggered via CLI `python main.py --once` / programmatic invocation of `utils.dna_ui.main()`.

### 2. Inputs
- `data/raw/toSequence.txt`: Text file containing 1 or more DNA strings (one string per non-empty line).
- `rules/*.json`: Rule definition files for variable domain matching and parsing.

### 3. Terminal States
- **SUCCESS**: All new DNA strings in `toSequence.txt` are parsed (or captured as parse errors), results atomically committed to JSON/CSV output files, ledger updated, and input file truncated by watcher/runner.
- **DEDUPLICATED (SKIPPED)**: Input DNA strings already exist in `data/processed_ledger.json`. No redundant file system modifications occur.
- **FAILURE / ABORTED**: I/O, persistence, or rule load errors occur. Output files and ledger remain unchanged, exception is raised, and input file is NOT cleared (preventing data loss).

### 4. Invariants
- **Atomicity**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are updated atomically. No partial/torn writes occur if execution crashes during write.
- **Input Preservation on Failure**: If processing or file persistence fails, `toSequence.txt` MUST NOT be cleared.
- **Deduplication Consistency**: Processing the exact same DNA string multiple times yields identical outputs with zero duplicate side-effects.

### 5. Error Classes
- `DNAProcessingError` (Base Exception)
  - `RuleLoadError`: Raised when rules directory or rule JSONs cannot be initialized.
  - `PersistenceError`: Raised when writing or atomically renaming output/ledger files fails.
  - `RuleParseError`: Captured per-DNA sequence when string structure does not conform to rulesets.

### 6. Idempotency Key
- **Key**: Raw DNA string value (e.g., `VOL08900750712`).
- **Store**: `data/processed_ledger.json`.

### 7. Atomicity Boundary
- Temporary directory staging under `data/output/` followed by `os.replace` (atomic rename) for JSON and CSV outputs.
- Staged temporary file write followed by `os.replace` for `processed_ledger.json`.
- Truncation of `data/raw/toSequence.txt` in `main.py` ONLY after `utils.dna_ui.main()` succeeds completely.

### 8. Required Logs & Telemetry
- `[Idempotency] key={key} dedupe_hit={bool} terminal_outcome={outcome}`
- `[OK] Processed {count} new DNA strings. Total in ledger: {total}`
- `[{timestamp}][Watcher][CRITICAL] DNA processing failed: {error}`

---

## Grep Recipes

1. **Track Deduplication & Idempotency Hits:**
   ```bash
   grep "\[Idempotency\]" data/output/*.log 2>/dev/null || grep -r "\[Idempotency\]" .
   ```

2. **Monitor Watcher Failures & Errors:**
   ```bash
   grep "\[Watcher\]\[CRITICAL\]" main.log 2>/dev/null || grep -r "\[Watcher\]" .
   ```
