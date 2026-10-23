# Chain Contract: DNA Batch Parsing

## Overview
The DNA Batch Parsing chain is responsible for watching or running batch operations over DNA sequences contained in `data/raw/toSequence.txt`, evaluating them against rules in `rules/`, appending structured results into cumulative JSON and CSV outputs in `data/output/`, and recording terminal outcomes in `data/processed_ledger.json`.

---

## Contract Specification

### 1. Trigger
- **Watcher Mode**: Triggered automatically in `main.py` when `data/raw/toSequence.txt` contains new non-empty content.
- **Single-Run Mode**: Triggered manually via CLI flag `python main.py --once` or directly via `utils/dna_ui.main()`.

### 2. Inputs
- `data/raw/toSequence.txt`: Text file with one raw DNA string per line (e.g. `VOL08900750712`).
- `rules/rules_*.json`: Rule configuration files parsed by `DNACalculator`.

### 3. Terminal States
- `success`: DNA sequence parsed successfully against rules.
- `error`: Rule validation or parsing failed for the DNA sequence (e.g., `RuleParseError`).

### 4. Invariants
- **Idempotency**: DNA sequences already recorded in `data/processed_ledger.json` are skipped (no duplicate entries appended to output files).
- **Atomicity**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are written atomically. Partial or torn writes never affect output state.
- **Input Retention on Failure**: `data/raw/toSequence.txt` is cleared ONLY if batch execution completes successfully without exceptions.

### 5. Error Classes
- `DNAProcessingError`: Base class for DNA processing exceptions.
- `RuleLoadError`: Raised when rules cannot be loaded from `rules/`.
- `PersistenceError`: Raised when atomic file I/O or rename fails.

### 6. Idempotency Key
- Key: The trimmed raw DNA string itself (`dna_str`).
- Storage: `data/processed_ledger.json` mapping `key -> {'terminal_outcome': 'success'|'error: ...', 'timestamp': 'YYYY-MM-DD HH:MM:SS'}`.

### 7. Atomicity Boundary
- All modified outputs (`toSequence_parsed.json` and `toSequence_parsed.csv`) are written to temporary files within a `tempfile.TemporaryDirectory` located inside `data/output/`.
- Each temp file stream is explicitly flushed (`jf.flush()`) and synced to physical disk (`os.fsync(jf.fileno())`).
- Temp files are atomically renamed to final destinations using `os.replace()`.
- Upon successful output replacement, `processed_ledger.json` is updated.

### 8. Required Logs
- **Idempotency Check (Hit)**: `[Idempotency] key={key} dedupe_hit=True terminal_outcome={outcome}`
- **Idempotency Check (Miss)**: `[Idempotency] key={key} dedupe_hit=False terminal_outcome=processing`
- **Idempotency Execution Complete**: `[Idempotency] key={key} dedupe_hit=False terminal_outcome={outcome}`
- **Summary**: `[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {total_ledger_count}`

---

## Telemetry & Operational Grep Recipes

### Check deduplication hits and misses
```bash
grep "\[Idempotency\]" data/output/*.log 2>/dev/null || grep "\[Idempotency\]"
```

### Trace errors during batch execution
```bash
grep -E "\[CRITICAL\]|\[ERROR\]"
```
