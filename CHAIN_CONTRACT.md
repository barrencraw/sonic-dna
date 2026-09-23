# Chain Contract: DNA Batch Parsing

## Overview & Scope
The **DNA Batch Parsing** chain processes raw DNA sequence strings from `data/raw/toSequence.txt`, parses them according to modular rule definitions, and produces cumulative output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) along with an idempotency tracking ledger (`data/processed_ledger.json`).

---

## Contract Specification

### 1. Trigger
- **Watcher (`main.py`)**: File system event or polling on `data/raw/toSequence.txt`.
- **CLI / Manual (`main.py --once`)**: Invocation of `process_once()`.
- **Direct Python Call**: Invocation of `utils.dna_ui.run_batch()` (aliased as `main()`).

### 2. Inputs
- `data/raw/toSequence.txt`: Text file containing one DNA sequence string per line.
- `rules/*.json`: Variable rule configuration files used by `DNACalculator`.
- `data/processed_ledger.json` (optional existing): Idempotency state.
- `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv` (optional existing): Cumulative output stores.

### 3. Terminal States
- **SUCCESS**: All new DNA sequences in `toSequence.txt` parsed (or flagged with rule error), output files atomically written, ledger updated, and `toSequence.txt` cleared (if triggered via `main.py`).
- **NO_OP / SKIPPED**: `toSequence.txt` is missing, empty, or all contained sequences already exist in `processed_ledger.json`.
- **FAILURE (CRITICAL / ERROR)**: Unrecoverable error (e.g., rule loading failure, I/O / atomic write failure). Output files are unchanged, ledger is unmodified, and input file is retained for retry/investigation.

### 4. Invariants
- **Atomicity Boundary**: All outputs (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`) are updated atomically together or not at all.
- **Idempotency**: Processing the same DNA sequence string multiple times produces exactly one entry in the output files and ledger.
- **Data Preservation**: Input queue (`toSequence.txt`) is cleared ONLY after batch processing and atomic persistence succeed.
- **Strict Error Boundary**: Invalid individual DNA strings are recorded as parse error entries rather than causing total batch transaction rollback.

### 5. Error Taxonomy
- `DNAProcessingError`: Base class for errors in the DNA processing pipeline.
- `RuleParseError`: Raised when a DNA string does not match any rule definition or has invalid sub-variable values.
- `PersistenceError`: Raised when writing, flushing, fsyncing, or atomically replacing output or ledger files fails.

### 6. Idempotency Key Strategy
- **Key Definition**: The trimmed DNA sequence string itself (e.g., `VOL08900750712`).
- **Deduplication Logic**: Before parsing, `dna_str` is checked against `processed_ledger.json`.
- **Ledger Record**:
  ```json
  "VOL08900750712": {
    "terminal_outcome": "success",
    "timestamp": "2025-06-02 12:00:00"
  }
  ```

### 7. Atomicity Boundary & Implementation
- All output files are staged in a single temporary directory created within the output directory (`data/output/.tmp_*`).
- Temporary handles are `flush()`ed and `os.fsync()`ed prior to commit.
- Files are atomically replaced at their final path using `os.replace()`.
- If any operation fails during staging or atomic rename, a `PersistenceError` is raised and no destination files are touched.

### 8. Telemetry & Observability Log Format
Logs follow structured prefix patterns:
- `[Idempotency] key={key} dedupe_hit={True|False} terminal_outcome={outcome}`
- `[Watcher] ...`
- `[Once-Runner] ...`

---

## Telemetry Grep Recipes

1. **Check for Deduplication Hits:**
   ```bash
   grep "dedupe_hit=True" data/output/*.log || grep "[Idempotency]"
   ```

2. **Check for Parse Errors vs Successes:**
   ```bash
   grep "terminal_outcome="
   ```

3. **Check for Critical Processing Failures:**
   ```bash
   grep "\[CRITICAL\]"
   ```
