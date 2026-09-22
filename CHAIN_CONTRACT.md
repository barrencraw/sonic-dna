# Chain Contract: DNA Batch Parsing

## Overview
This contract governs the **DNA Batch Parsing** chain (`main.py` watcher / once-runner and `utils/dna_ui.py`).

## Contract Specifications

### 1. Trigger
- Manual or scheduled invocation of `python main.py --once`.
- Background watcher loop in `main.py` detecting new non-empty lines in `data/raw/toSequence.txt`.

### 2. Inputs
- Input queue file: `data/raw/toSequence.txt` (UTF-8 plain text, 1 DNA string per line).
- Rule files: `rules/rules_*.json` defining variable specifications and prefix mappings.
- Processed Ledger: `data/processed_ledger.json`.

### 3. Terminal States
- **SUCCESS**: All new DNA strings parsed and recorded; `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` updated; `toSequence.txt` truncated (drained).
- **SKIP**: Input file empty or all DNA strings already exist in `processed_ledger.json` (`dedupe_hit=True`). Output files unchanged.
- **FAILURE / CRITICAL**: Transient I/O, persistence, or rule load errors occur (`DNAProcessingError`, `RuleLoadError`, `PersistenceError`). Output files remain uncorrupted; `toSequence.txt` is NOT cleared so processing can be retried.

### 4. Invariants
- **No Partial/Torn Writes**: JSON and CSV output files are written to temporary files, flushed (`jf.flush()`, `os.fsync()`), and atomically renamed via `os.replace()`.
- **Deduplication / Idempotency**: Each DNA string is keyed by its exact string content (`idempotency_key = dna_str`). Re-processing the same key skips parser logic and avoids duplicate entries.
- **Queue Draining Safety**: `toSequence.txt` is truncated ONLY if `run_batch()` completes without throwing an exception.

### 5. Error Taxonomy
- `DNAProcessingError`: Base class for DNA processing pipeline errors.
- `RuleLoadError`: Subclass raised when rule JSON files cannot be loaded.
- `PersistenceError`: Subclass raised when temp directory creation, atomic file writing, or renaming fails.
- `RuleParseError`: Raised per-item when an individual DNA string fails rule parsing (handled per item and recorded as `error` outcome in ledger/outputs).

### 6. Idempotency Key Strategy
- `idempotency_key = dna_str`
- Lookups against `data/processed_ledger.json` determine `dedupe_hit`.

### 7. Atomicity Boundary
- All output updates (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`) occur within a single atomic commit step (`new_processed_count > 0` condition with temp directory + fsync + os.replace).

### 8. Required Logs
- Deduplication status: `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- Batch completion: `[OK] Processed <count> new DNA strings. Total in ledger: <total>`
- Watcher failure: `[Watcher][CRITICAL] DNA processing failed: <error>` or `[Watcher][ERROR] Unexpected error: <error>`

### 9. Grep Recipes
```bash
# Check idempotency hits and misses
grep "\[Idempotency\]" logs.txt

# Check successful batch completions
grep "\[OK\] Processed" logs.txt

# Check batch parsing errors
grep "\[CRITICAL\] DNA processing failed:" logs.txt
```
