# DNA Batch Parsing Chain Contract

## 1. Overview & Trigger
- **Chain Name:** DNA Batch Parsing (`batch_parser`)
- **Trigger:**
  - Automatic: File watcher (`main.py`) detecting non-empty content in `data/raw/toSequence.txt`.
  - Manual / CLI: Single-run execution via `python main.py --once` or direct invocation of `run_batch()`.
- **Primary Function:** Parse DNA sequences into structured JSON/CSV domain outputs while enforcing idempotency, thermal overload protection, and atomic output persistence.

## 2. Inputs
- **`data/raw/toSequence.txt`**: Plaintext file containing one DNA sequence string per line.
- **Rules folder (`rules/`)**: JSON schema definitions for DNA rule prefixes (e.g., Volume, Timbre, Dynamics).
- **Processed Ledger (`data/processed_ledger.json`)**: Persisted ledger storing idempotency states and thermal system state.

## 3. Terminal States & Status Enum (`DNAStatus`)
Every processed DNA sequence reaches one of the following lowercase terminal states:
- **`success`**: DNA sequence parsed successfully according to rule schema. Output appended to cumulative JSON and CSV files.
- **`error`**: DNA sequence failed parsing against active rules (e.g., `RuleParseError`). Error details recorded in output and ledger.
- **`skipped`**: Sequence key already present in ledger with a terminal outcome (`success` or `error`). Re-computation skipped.
- **`refused`**: Core state refused processing (e.g., `ThermalOverloadError` due to thermal lockout). Sequence left unprocessed in input file.

## 4. Invariants
1. **Idempotency Invariant:** A DNA sequence present in the ledger with `success` or `error` is never re-parsed or duplicate-written.
2. **Atomic Write Invariant:** Output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) and `processed_ledger.json` are written atomically via tempfile + `flush` + `fsync` + `replace`.
3. **Thermal Boundary Invariant:** Each processed sequence adds 2.0 heat units. Safety lockout threshold is 10.0 heat units. Heat dissipates at 0.5 units/second.
4. **No Silent Drain Invariant:** If batch processing fails or is refused due to `ThermalOverloadError`, `toSequence.txt` is NOT cleared by `main.py`.

## 5. Error Taxonomy
Inheriting from base `DNAProcessingError` or `PersistenceError`:
- `DNAProcessingError` (Base)
  - `RuleLoadError`: Rules folder or JSON schema failed loading.
  - `InputReadError`: Input file read failure.
  - `ThermalOverloadError`: System core heat exceeded lockout threshold (10.0).
- `PersistenceError` (Base)
  - `LedgerLoadError`: Corrupted JSON ledger file.
  - `LedgerSaveError`: Ledger file write failure.
  - `AtomicWriteError`: Tempfile creation, flush, fsync, or rename failure.

## 6. Idempotency Key Strategy
- **Key Format:** The raw DNA sequence string itself (e.g., `VOL08900750712`).
- **Ledger Storage:** Stored in `data/processed_ledger.json` under `ledger[idempotency_key]` with `terminal_outcome` and `timestamp`.

## 7. Atomicity Boundary
1. Temp files created in `data/output/` directory.
2. Formatted JSON and CSV content written to temp files.
3. `flush()` and `os.fsync(fileno)` called on file descriptors to commit data to physical storage.
4. Atomic `os.replace()` overwrites destination files.
5. Ledger saved atomically.
6. JSON and CSV writes are executed ONLY if `new_processed_count > 0`.

## 8. Telemetry & Required Structured Logs
Structured JSON telemetry logs emitted via `log_structured()` prefixed with `JSON_LOG:`:
- `timestamp`: UTC ISO 8601 string (`YYYY-MM-DDTHH:MM:SSZ`).
- `correlation_id`: Unique trace ID per batch run.
- `actor_id`: Entity executing chain (default `'batch_parser'`).
- `chain_name`: `'dna_batch_parser'`.
- `step`: Current step (`start`, `parse_item`, `persist_outputs`, `end`, `error`).
- `outcome`: Terminal state or step status (`success`, `error`, `skipped`, `refused`).
- `latency_ms`: Execution time in milliseconds.
- `idempotency_key`: DNA sequence string.
- `outcome_detail`: Context detail or error message.

## 9. Grep Recipes
- **All Structured Telemetry Logs:**
  ```bash
  grep "JSON_LOG:" logs.txt
  ```
- **Track Specific Trace / Correlation ID:**
  ```bash
  grep "correlation_id" logs.txt | grep "<UUID>"
  ```
- **Find Thermal Lockouts / Refusals:**
  ```bash
  grep "Thermal Lockout" logs.txt
  ```
- **Inspect Atomic Persistence Failures:**
  ```bash
  grep "AtomicWriteError" logs.txt
  ```
