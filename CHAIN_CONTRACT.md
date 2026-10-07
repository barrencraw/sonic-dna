# DNA Batch Parsing Chain Contract

## 1. Chain Overview
- **Chain Name:** `dna_batch_parsing`
- **Trigger:** Watcher detecting new DNA sequences in `data/raw/toSequence.txt` or CLI invocation (`python main.py --once`).
- **Inputs:** `data/raw/toSequence.txt` containing newline-separated DNA sequence strings (`dna_sequence`).

## 2. Terminal States & Status Taxonomy
- `success`: DNA sequence successfully parsed by rule matching prefix and appended to output data structures.
- `error`: Rule parse error occurred (e.g. `RuleParseError`), error recorded in output data structures.
- `skipped`: DNA sequence already recorded in ledger with a terminal outcome (deduplication hit).
- `refused`: Execution aborted before processing due to bad system state or fatal rule loading error.

## 3. Invariants
- **Consistency:** Outputs in `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` remain completely aligned.
- **Atomicity:** All files (`json`, `csv`, `ledger`) are updated atomically or none are modified. Input queue (`toSequence.txt`) is cleared only after successful batch completion.
- **Idempotency:** Re-processing the same DNA sequence returns `dedupe_hit=True` and produces no duplicate output records.

## 4. Error Taxonomy
- `DNAProcessingError` (Base Exception)
  - `RuleLoadError`: Raised when rules directory or rule JSONs cannot be initialized.
  - `InputReadError`: Raised when `data/raw/toSequence.txt` cannot be read.
  - `PersistenceError`: Raised on IO or atomic rename failure.
    - `LedgerLoadError`: Raised when loading `processed_ledger.json` fails due to corruption.
    - `LedgerSaveError`: Raised when saving `processed_ledger.json` fails.
    - `AtomicWriteError`: Raised when atomic staged file rename or write fails.

## 5. Idempotency Key & Deduplication
- **Key:** `dna_sequence` string (e.g. `VOL08900750712`).
- **Store:** `data/processed_ledger.json`
- **Dedupe Strategy:** If `dna_sequence` exists in `processed_ledger.json` with a terminal outcome (`success` or `error`), skip parsing and do not duplicate in output files.

## 6. Atomicity Boundary
- Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are written to a temporary directory under the target folder, flushed to disk with `os.fsync()`, and atomically moved into position via `os.replace()`.
- Truncation of input file `data/raw/toSequence.txt` occurs only after atomic persistence succeeds.

## 7. Required Telemetry Logs
- Structured telemetry JSON logs prefixed with `JSON_LOG:` containing:
  - `timestamp`: UTC ISO 8601 string.
  - `correlation_id`: Unique trace identifier (UUID v4).
  - `actor_id`: Component name (e.g. `batch_parser`).
  - `chain_name`: `dna_batch_parsing`.
  - `step`: Pipeline stage (`start`, `parse_sequence`, `persist_outputs`, `end`).
  - `outcome`: `success`, `error`, `skipped`, or `refused`.
  - `latency_ms`: Duration in milliseconds.
  - `idempotency_key`: `dna_sequence` or batch identifier.
  - `outcome_detail`: Contextual diagnostic message.

## 8. Log Grep Recipes
- Filter all telemetry logs:
  ```bash
  grep "JSON_LOG:" app.log
  ```
- Trace a specific batch execution by correlation ID:
  ```bash
  grep "JSON_LOG:" app.log | grep '"correlation_id": "<CORRELATION_ID>"'
  ```
- Find all deduplication skip events:
  ```bash
  grep "JSON_LOG:" app.log | grep '"outcome": "skipped"'
  ```
