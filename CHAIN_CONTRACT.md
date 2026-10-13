# Chain Contract: DNA Batch Parsing Chain

## Overview
The DNA Batch Parsing Chain processes raw DNA sequences from `data/raw/toSequence.txt`, parses them according to rules in `rules/`, and atomically persists cumulative parsed results to `data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`, and updates `data/processed_ledger.json`.

---

## 1. Trigger
- **Manual / Batch Trigger**: Direct execution of `main.py --once` or invocation of `utils.dna_ui.run_batch()`.
- **Automated Watcher Trigger**: `main.py` watcher loop detecting new non-empty content in `data/raw/toSequence.txt`.

---

## 2. Inputs
- `input_file`: `data/raw/toSequence.txt` containing one DNA sequence per line (e.g., `VOL08900750712`).
- `rules_folder`: `rules/` containing JSON rule specifications.
- `ledger_file`: `data/processed_ledger.json` tracking previously processed idempotency keys.
- `output_files`: `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`.

---

## 3. Terminal States
- `SUCCESS`: Sequence parsed successfully and recorded in ledger and output stores.
- `ERROR`: Sequence parsing failed due to `RuleParseError` or invalid input format, recorded as error in ledger and output stores.
- `SKIPPED`: Sequence already exists in `processed_ledger.json` (idempotency key collision / deduplication hit).
- `ABORTED`: Execution aborted due to unrecoverable exception (e.g., `RuleLoadError`, `InputReadError`, `PersistenceError`). Output files remain unmodified.

---

## 4. Invariants
- **Deduplication Invariant**: A DNA sequence present in `data/processed_ledger.json` is never re-parsed or appended again to `toSequence_parsed.json` / `toSequence_parsed.csv`.
- **Atomicity Invariant**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `data/processed_ledger.json` are committed atomically using temporary directory writes and `os.replace`. Partial/torn writes never reach `data/output/`.
- **Watcher Safety Invariant**: `data/raw/toSequence.txt` is cleared IF AND ONLY IF `run_batch()` completes without raising a critical exception.

---

## 5. Error Classes
- `DNAProcessingError`: Base exception class for DNA parsing chain errors.
- `RuleLoadError`: Raised when loading JSON rule definitions from `rules/` fails.
- `InputReadError`: Raised when reading `data/raw/toSequence.txt` fails.
- `PersistenceError`: Raised when writing temporary files, syncing to disk (`fsync`), or replacing target output files fails.

---

## 6. Idempotency Key
- **Definition**: The trimmed, non-empty DNA sequence string (e.g., `VOL08900750712`).
- **Storage**: Key in `data/processed_ledger.json` dictionary mapping to `{'terminal_outcome': outcome, 'timestamp': ISO8601_TIMESTAMP}`.

---

## 7. Atomicity Boundary
- All output mutations are staged in a temporary directory on the same filesystem (`dir=output_folder`).
- File handles are flushed (`flush()`) and synced (`os.fsync()`) before `os.replace()`.
- Ledger saving and atomic file replacement occur together at the end of successful batch execution.

---

## 8. Required Logs & Telemetry
Structured telemetry JSON logs emitted to stdout/stderr with mandatory fields:
- `timestamp`: UTC ISO 8601 format.
- `correlation_id`: Trace ID across batch run.
- `actor_id`: Initiator identification (e.g. `batch_parser` or `watcher`).
- `chain_name`: `"dna_batch_parser"`.
- `step`: Process step (`"start"`, `"dedupe_check"`, `"parse_sequence"`, `"atomic_commit"`, `"end"`).
- `outcome`: `"success"`, `"error"`, or `"skipped"`.
- `latency_ms`: Duration of operation in milliseconds.
- `idempotency_key`: DNA sequence string.

---

## 9. Grep Recipes for Operational Telemetry
- **Find all batch start/end events**:
  ```bash
  grep '"chain_name": "dna_batch_parser"' | grep -E '"step": "(start|end)"'
  ```
- **Find deduplication hits**:
  ```bash
  grep '"step": "dedupe_check"' | grep '"outcome": "skipped"'
  ```
- **Find parsing errors**:
  ```bash
  grep '"chain_name": "dna_batch_parser"' | grep '"outcome": "error"'
  ```
