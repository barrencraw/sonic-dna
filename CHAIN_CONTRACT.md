# Chain Contract: DNA Batch Parsing Chain

## Overview
The **DNA Batch Parsing Chain** consumes DNA sequence strings from `data/raw/toSequence.txt`, parses them into modular sound property structures using rule definitions (`rules/rules_*.json`), and persists the results atomically into cumulative outputs (`data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`) and a execution tracking ledger (`data/processed_ledger.json`).

---

## Contract Specification

### 1. Trigger
- **Watcher Loop (`main.py`):** Background thread watching `data/raw/toSequence.txt` for non-empty changes.
- **CLI Batch Execution (`main.py --once` / `utils/dna_ui.py`):** Explicit programmatic or command-line invocation of `run_batch(correlation_id=None)`.

### 2. Inputs
- `data/raw/toSequence.txt`: Plaintext file with one DNA sequence string per non-empty line.
- `rules/rules_*.json`: Rule definition files for parsing sound variables (e.g. Volume, Timbre).

### 3. Terminal States
- `SUCCESS`: Output JSON/CSV files and `processed_ledger.json` updated atomically; `toSequence.txt` cleared (if invoked via watcher/once runner).
- `ERROR`: Typed exception raised (`DNAProcessingError`, `RuleLoadError`, `PersistenceError`); transaction rolled back without modifying existing output files; `toSequence.txt` left intact for retry.

### 4. Invariants
- **No Torn Writes:** JSON, CSV, and ledger writes are zero-or-all; partial file writes are forbidden.
- **Data Alignment:** Every entry in `toSequence_parsed.json` corresponds to a matching row in `toSequence_parsed.csv`.
- **Idempotent Storage:** Double-invoking `run_batch()` on identical DNA sequence strings yields zero new output entries or duplicate side effects.

### 5. Error Taxonomy
- `DNAProcessingError`: Base class for DNA batch parsing failures.
- `RuleLoadError(DNAProcessingError)`: Failed to read or parse rule JSON definitions from `rules/`.
- `PersistenceError(DNAProcessingError)`: Atomic directory creation, write, fsync, or rename failure for output files or ledger.

### 6. Idempotency Key Strategy
- **Idempotency Key:** DNA Sequence string (e.g., `VOL08900750712`).
- **Ledger Storage:** `data/processed_ledger.json` maps `idempotency_key` -> `{ 'terminal_outcome': 'success' | 'error: ...', 'timestamp': 'YYYY-MM-DD HH:MM:SS' }`.

### 7. Atomicity Boundary
1. Write JSON output, CSV output, and updated ledger to temporary files in a single isolated temp directory inside the target folder using `tempfile.TemporaryDirectory`.
2. Flush buffers (`file.flush()`) and force physical disk sync (`os.fsync(file.fileno())`).
3. Atomically commit files using `os.replace(tmp_path, target_path)`.
4. Only upon successful completion of step 3, truncate `data/raw/toSequence.txt` (in `main.py`).

### 8. Telemetry & Required Logs
- **Start Log:** `[BatchParser][START] correlation_id={correlation_id} input_file={input_file}`
- **Dedupe Hit Log:** `[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={outcome}`
- **Dedupe Miss Log:** `[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}`
- **End Log:** `[BatchParser][END] correlation_id={correlation_id} processed_count={count} total_ledger={total}`

---

## Grep Recipes

Filter telemetry logs for batch execution and idempotency tracking:
```bash
# Track batch processing lifecycle:
grep "\[BatchParser\]" logs.txt

# Inspect idempotency deduplication decisions:
grep "\[Idempotency\]" logs.txt

# Inspect dedupe hits vs misses:
grep "dedupe_hit=True" logs.txt
grep "dedupe_hit=False" logs.txt

# Filter by correlation ID:
grep "correlation_id=YOUR_UUID" logs.txt
```
