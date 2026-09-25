# Chain Contract: DNA Batch Parsing

## Overview
This document specifies the formal contract for the **DNA Batch Parsing** chain (`main.py` watcher / once-runner and `utils/dna_ui.py` batch parser).

---

## Contract Specification

### 1. Trigger
- File modification event on `data/raw/toSequence.txt` observed by the watcher (`main.py`).
- Direct command-line trigger via `python main.py --once`.

### 2. Inputs
- `data/raw/toSequence.txt`: A plain-text file containing one DNA sequence string per line (e.g., `VOL08900750712`).
- Rules definitions located in `rules/rules_*.json`.

### 3. Terminal States
- `SUCCESS`: All new non-duplicate DNA sequences are parsed, added to cumulative JSON/CSV output files, recorded in the processed ledger, and `data/raw/toSequence.txt` is cleared.
- `SKIPPED`: `data/raw/toSequence.txt` is empty or all contained sequences have already been processed according to the ledger; output files and input file remain unmodified.
- `ERROR`: A failure occurred (rule loading failure, input read error, or persistence failure during atomic write). `data/raw/toSequence.txt` is preserved so data is not lost and can be retried.

### 4. Invariants
- **Idempotency:** A DNA sequence with the same string key is processed at most once. Re-submitting an already processed key does not create duplicate entries in output files or ledger.
- **Atomicity:** Updates to `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv` occur atomically via temporary file writes, `fsync`, and atomic renames (`os.replace`). Output files are never left in a partially written or corrupted state.
- **No Silent Input Drains:** `data/raw/toSequence.txt` is cleared ONLY after `run_batch()` completes without unhandled exceptions.

### 5. Error Taxonomy
- `DNAProcessingError`: Base exception class for DNA processing errors.
- `RuleLoadError` (subclass of `DNAProcessingError`): Raised when rules fail to load from `rules/`.
- `PersistenceError` (subclass of `DNAProcessingError`): Raised when writing or replacing output files or ledger fails.

### 6. Idempotency Key
- Key: `dna_sequence` (the raw trimmed string from `toSequence.txt`).
- Ledger: `data/processed_ledger.json` storing mapped entries: `{ "<dna_sequence>": { "terminal_outcome": "<outcome>", "timestamp": "<ISO timestamp>" } }`.

### 7. Atomicity Boundary
- Transaction scope: Single batch processing invocation.
- Write sequence: Write outputs to temporary files inside a temp directory in `data/output/` -> `flush()` & `fsync()` -> `save_ledger()` -> `os.replace()` temp files to `toSequence_parsed.json` and `toSequence_parsed.csv`.

### 8. Required Logs & Telemetry
- Batch Start: `[BatchParser] Starting batch processing...`
- Idempotency Skip (Dedupe Hit): `[Idempotency] key=<key> dedupe_hit=True terminal_outcome=<outcome>`
- Idempotency Process (Dedupe Miss): `[Idempotency] key=<key> dedupe_hit=False terminal_outcome=<outcome>`
- Batch End: `[BatchParser] Batch complete. Processed <N> new DNA strings. Total in ledger: <total>`

---

## Grep Recipes

```bash
# Filter deduplication hits
grep "dedupe_hit=True" logs.txt

# Inspect terminal outcomes
grep "terminal_outcome=" logs.txt

# Monitor batch start and completion events
grep "BatchParser" logs.txt
```
