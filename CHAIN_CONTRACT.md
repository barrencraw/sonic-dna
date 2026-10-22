# Mini Chain Contract: DNA Batch Parsing

## Overview
The DNA Batch Parsing chain is responsible for reading raw DNA sequence strings from `data/raw/toSequence.txt`, parsing them using configured rules in `rules/`, tracking idempotency in `data/processed_ledger.json`, and atomically persisting results to `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`.

---

## Contract Specification

### 1. Trigger
- **Watcher Thread (`main.py`)**: Periodically checks `data/raw/toSequence.txt` for non-empty content.
- **Once-Runner CLI (`main.py --once`)**: Invokes single batch processing on execution.

### 2. Inputs
- `data/raw/toSequence.txt`: UTF-8 text file containing one DNA sequence per line (e.g., `VOL08900750712`).
- `rules/*.json`: Rule specification files (e.g., `rules_Volume.json`).

### 3. Terminal States
- **`success`**: DNA sequence parsed successfully against a matching rule.
- **`error: <reason>`**: Sequence parsing failed (e.g., `RuleParseError` due to unknown rule or invalid range).
- **`skipped`**: Sequence key already present in `data/processed_ledger.json` with a terminal state.

### 4. Invariants
- **Atomicity**: Output JSON (`toSequence_parsed.json`), output CSV (`toSequence_parsed.csv`), and ledger (`processed_ledger.json`) are updated atomically. No partial/torn file writes occur if execution is interrupted during disk I/O.
- **Deduplication**: Processing a previously observed sequence key does not generate duplicate entries in cumulative output files or re-parse the string.
- **Queue Clearing**: `data/raw/toSequence.txt` is cleared ONLY if `run_batch()` completes without throwing an exception. On persistence or parsing failure, `toSequence.txt` retains its contents for retry.

### 5. Error Taxonomy
- `DNAProcessingError`: Base exception for all batch parsing domain failures.
- `RuleLoadError` (subclass of `DNAProcessingError`): Raised when rule definition files cannot be loaded from disk.
- `PersistenceError` (subclass of `DNAProcessingError`): Raised when writing or atomically committing output/ledger files fails.

### 6. Idempotency Key Strategy
- **Key Definition**: The raw DNA sequence string itself (e.g., `VOL08900750712`).
- **Ledger Storage**: Stored in `data/processed_ledger.json` mapped to terminal outcome and timestamp.

### 7. Atomicity Boundary
1. Write JSON and CSV output files to a temporary directory created on the target filesystem (`data/output/`).
2. Flush file buffers (`jf.flush()`) and force sync to physical disk (`os.fsync(jf.fileno())`).
3. Commit using atomic rename (`os.replace`) to replace target files.
4. Update `data/processed_ledger.json` atomically.

### 8. Required Telemetry & Logs
- **Start / Step / End logs**:
  - `[Watcher] New DNA detected → running parser…`
  - `[Idempotency] key=<key> dedupe_hit=<bool> terminal_outcome=<outcome>`
  - `[OK] Processed <count> new DNA strings. Total in ledger: <total>`

---

## Grep Recipes

- **Trace idempotency hits**:
  ```bash
  grep "\[Idempotency\]" logs/*.log
  ```
- **Trace critical processing errors**:
  ```bash
  grep "\[CRITICAL\]" logs/*.log
  ```
- **Verify batch completion**:
  ```bash
  grep "\[OK\] Processed" logs/*.log
  ```
