# Chain Contract: DNA Batch Parsing

## Overview
This document specifies the contract governing the DNA Batch Parsing chain (`utils/dna_ui.py`, `main.py`).

---

## 1. Trigger
- **Automated**: File watcher monitoring `data/raw/toSequence.txt` for new DNA sequences.
- **Manual/Programmatic**: Direct execution via `utils.dna_ui.main()` or `run_batch()`, or `python main.py --once`.

---

## 2. Inputs
- `data/raw/toSequence.txt`: Text file containing newline-delimited DNA sequences (e.g., `VOL08900750712`).
- `rules/*.json`: JSON rulesets defining variables, prefixes, and schema constraints.
- `data/processed_ledger.json`: Ledger tracking idempotency keys and terminal states of processed sequences.

---

## 3. Terminal States
- **`success`**: Sequence was parsed matching a loaded rule schema; entry appended to `toSequence_parsed.json`, flattened row appended to `toSequence_parsed.csv`, and recorded in `processed_ledger.json`.
- **`error`**: Sequence prefix or value structure was invalid according to rules; error entry recorded in `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json`.
- **`skipped`**: Sequence key was already found in `processed_ledger.json`. No redundant computation or duplicate entry added to output files.

---

## 4. Invariants
- **Deduplication**: Processing same DNA sequence multiple times produces identical output state without duplicate rows/entries.
- **Atomic Persistence**: Outputs (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` update atomically. Unhandled exceptions during file writing or flush abort the operation and leave previous output files intact.
- **Queue Protection**: The input file (`toSequence.txt`) is cleared only after `run_batch()` completes without persistence errors.

---

## 5. Error Taxonomy
- `DNAProcessingError`: Base class for processing errors.
- `RuleLoadError`: Raised when rules directory or JSON files fail to load.
- `PersistenceError`: Raised when writing temporary files or performing atomic renames fails.

---

## 6. Idempotency Strategy
- **Idempotency Key**: DNA sequence string (e.g., `VOL08900750712`).
- **Ledger Storage**: Key mapped to `{'terminal_outcome': outcome, 'timestamp': ISO_TIMESTAMP}` in `data/processed_ledger.json`.

---

## 7. Atomicity Boundary
1. Write JSON and CSV outputs into a temporary directory (`tempfile.TemporaryDirectory`) located inside the target `output_folder`.
2. Explicitly `flush()` and `os.fsync()` file handles.
3. Commit files atomically using `os.replace(tmp_file, target_path)`.

---

## 8. Required Telemetry & Logs
Structured console logging includes:
- `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `[OK] Parsed <N> DNA strings.`
- `[OK] Processed <N> new DNA strings. Total in ledger: <M>`

### Grep Recipes
- **Find deduplication hits**:
  `grep "dedupe_hit=True" log.txt`
- **Find terminal outcomes**:
  `grep "terminal_outcome=" log.txt`
