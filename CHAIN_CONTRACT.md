# Chain Contract: DNA Batch Parsing

## Overview
The **DNA Batch Parsing** chain reads structured audio DNA sequences from `data/raw/toSequence.txt`, parses sub-variable rules via `DNACalculator`, appends structured JSON and flattened CSV entries to `data/output/`, and updates the processed ledger `data/processed_ledger.json`.

---

## Contract Specification

### 1. Trigger
- Continuous background watcher (`main.py` -> `watch_loop()`) monitoring `data/raw/toSequence.txt`
- One-time CLI batch runner (`python main.py --once` -> `process_once()`)
- Direct invocation (`utils/dna_ui.py` -> `run_batch()`)

### 2. Inputs
- `data/raw/toSequence.txt`: Text file containing newline-separated DNA sequences (e.g., `VOL08900750712`)
- `rules/*.json`: Variable definitions and validation schemas
- `data/processed_ledger.json`: Historical ledger tracking processed DNA sequences and terminal outcomes

### 3. Terminal States
- `success`: DNA sequence parsed and appended to JSON and CSV outputs.
- `error: <message>`: DNA sequence failed rule parsing (e.g., `RuleParseError`), captured in JSON/CSV output as an error entry.

### 4. Invariants
- **Idempotency:** Re-invoking the chain with an already processed DNA sequence is a no-op; duplicate entries are never added to `toSequence_parsed.json` or `toSequence_parsed.csv`.
- **Atomicity:** All file persistence operations (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`) use an atomic temp-file write-and-replace strategy (`os.replace`). Output files are either completely updated or untouched.
- **Input Queue Safety:** `data/raw/toSequence.txt` is cleared by the caller (`main.py`) only if `run_batch()` completes without throwing a `PersistenceError` or unhandled exception.

### 5. Error Taxonomy
- `DNAProcessingError`: Base class for DNA processing failures.
- `RuleLoadError` (subclass of `DNAProcessingError`): Raised when rule definitions in `rules/` fail to load.
- `PersistenceError` (subclass of `DNAProcessingError`): Raised when write, flush, sync, or atomic rename operations fail.

### 6. Idempotency Key
- The raw, stripped DNA sequence string itself (e.g., `VOL08900750712`).

### 7. Atomicity Boundary
- Temporary directory created inside `data/output/` using `tempfile.TemporaryDirectory`.
- Outputs written, flushed (`jf.flush()`), synced to physical media (`os.fsync(jf.fileno())`), and atomically replaced (`os.replace()`).

### 8. Required Telemetry & Logging
- Start log: `[BatchParser] Starting DNA batch parser...`
- Key deduplication: `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- Batch completion: `[BatchParser] Processed <count> new DNA strings. Total in ledger: <total>`

---

## Grep Recipes

- **Trace Idempotency Hits:**
  ```bash
  grep "dedupe_hit=True" application.log
  ```
- **Trace Failed Parses:**
  ```bash
  grep "terminal_outcome=error" application.log
  ```
- **Trace Batch Execution Summaries:**
  ```bash
  grep "BatchParser" application.log
  ```
