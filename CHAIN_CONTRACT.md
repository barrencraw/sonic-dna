# Mini Chain Contract: DNA Batch Processing Chain

## Overview
The DNA Batch Processing chain reads raw DNA sequences from `data/raw/toSequence.txt`, parses them against defined rules in `rules/`, records idempotency state in `data/processed_ledger.json`, and outputs cumulative structured data in `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`.

## Contract Specification

### 1. Trigger
- Manual execution via `python main.py --once`
- Background watcher loop in `main.py` detecting changes to `data/raw/toSequence.txt`
- Direct program invocation via `run_batch()` in `utils/dna_ui.py`

### 2. Inputs
- Input File: `data/raw/toSequence.txt` (UTF-8 text file with one DNA sequence per line)
- Rules: JSON rule files in `rules/` directory (e.g. `rules_Volume.json`)
- State Ledger: `data/processed_ledger.json`

### 3. Terminal States
- `success`: DNA sequence parsed successfully; result appended to output datasets and logged in ledger.
- `error`: DNA sequence failed rule parsing (`RuleParseError`); error outcome appended to output datasets and logged in ledger.
- `skipped`: DNA sequence already recorded in `processed_ledger.json` (`dedupe_hit=True`); processing bypassed.

### 4. Invariants
- **Atomicity**: Output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) and the processing ledger are updated atomically via temp-file writes and atomic renames (`os.replace`). No partial or torn writes exist on failure.
- **Idempotency**: Repeated execution with the same DNA sequence produces identical outcomes and does not create duplicate entries in output datasets or ledger.
- **Input File Integrity**: `toSequence.txt` is truncated/cleared if and only if batch processing succeeds without critical persistence exceptions.

### 5. Error Taxonomy
- `DNAProcessingError`: Base exception class for DNA processing failures.
- `PersistenceError` (subclass of `DNAProcessingError`): Raised when write, sync, or atomic move of output/ledger files fails.
- `RuleParseError`: Raised when a specific DNA sequence fails parsing rules.

### 6. Idempotency Key
- `idempotency_key = dna_sequence.strip()`

### 7. Atomicity Boundary
- Temporary directory under `data/output/` created per batch write.
- Outputs written, flushed (`jf.flush()`), synced to disk (`os.fsync()`), and atomically moved via `os.replace()`.

### 8. Required Telemetry & Logs
- Start: `[Idempotency] key=<key> dedupe_hit=False terminal_outcome=processing`
- Idempotency Hit: `[Idempotency] key=<key> dedupe_hit=True terminal_outcome=<outcome>`
- Batch End: `[OK] Processed <count> new DNA strings. Total in ledger: <total>`
- Critical Error: `[Watcher][CRITICAL] DNA processing failed: <error>`

### 9. Telemetry Grep Recipes
```bash
# Check idempotency deduplication hits
grep "\[Idempotency\]" logs.txt | grep "dedupe_hit=True"

# Monitor batch completion status
grep "\[OK\] Processed" logs.txt

# Filter critical processing errors
grep -E "\[CRITICAL\]|\[ERROR\]" logs.txt
```
