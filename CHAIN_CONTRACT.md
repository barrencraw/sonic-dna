# DNA Batch Parsing Chain Contract

This document specifies the formal contract for the DNA Batch Parsing chain, capturing its triggers, inputs, terminal states, invariants, error taxonomy, and observability guidelines.

## 1. Trigger
- **Watcher (`main.py`):** Initiated when file modification is detected in `data/raw/toSequence.txt`.
- **Once-Runner (`main.py --once`):** Explicit console/CLI execution.

## 2. Inputs
- A text file located at `data/raw/toSequence.txt` containing one DNA sequence per line.
- Optional: `correlation_id` passed dynamically to track the chain invocation.

## 3. Terminal States
- **`SUCCESS`**: One or more new DNA sequences were parsed successfully or recorded with error outcomes, and added to output datasets and the ledger.
- **`NO_NEW_ITEMS`**: All DNA sequences in the batch were already present in the ledger (or the batch was empty) and skipped.
- **`ERROR`**: The processing of the batch failed prematurely due to unhandled exceptions (e.g., config error or disk failure), causing a non-zero exit code.

## 4. Invariants
- **No Duplicate Side-Effects:** Processing the same DNA sequence multiple times does not result in redundant calculations, duplicated entries in JSON/CSV stores, or repeated heat accumulation.
- **No Silent Drains:** Processing errors and lockout safety violations must be propagated upstream, and the input file must not be cleared on failure.
- **Deduplication Persistence:** Deduplicated items (both successful and error-state results) are checked against the processed ledger before processing.

## 5. Error Taxonomy
The following exception classes under `utils/dna_ui.py` form the error taxonomy for batch processing:
- `DNAProcessingError`: The base class for all DNA parsing and persistence exceptions.
- `RuleLoadError`: Raised when DNA rule definitions fail to load.
- `InputReadError`: Raised when the input sequence file cannot be read.
- `PersistenceError`: The base class for storage-related failures.
- `LedgerSaveError`: Raised when the processed ledger fails to write atomically.
- `AtomicWriteError`: Raised when writing cumulative JSON or CSV output datasets atomically fails.

## 6. Idempotency Key
- The **DNA string itself** is the canonical idempotency key.
- Key lookup resides in the processed ledger (`data/processed_ledger.json`).

## 7. Atomicity Boundary
- All outputs (JSON, CSV, and the Ledger) are written using an atomic write pattern:
  1. Write output to a temporary file in the target directory.
  2. Flush (`f.flush()`) and fsync (`os.fsync(f.fileno())`) the file descriptor to physical disk.
  3. Perform atomic replacement (`os.replace()`) to prevent torn writes.
- If writing any output file fails, no existing files are modified, preserving eventual consistency.

## 8. Telemetry & Required Logs
All execution steps are logged in structured JSON format prefixed with `JSON_LOG:`.
Each log entry must contain the following fields:
- `timestamp`: UTC ISO 8601 string.
- `correlation_id`: Unique trace ID.
- `actor_id`: Initiator identification (defaults to `"system"`).
- `chain_name`: `"dna_batch_parser"`.
- `step`: Progression phase (`"start"`, `"idempotency_check"`, `"process_item"`, `"ledger_saving"`, `"atomic_write"`, `"end"`, `"cleanup_failure"`).
- `outcome`: Outcome of the step (`"success"`, `"skipped"`, `"error"`).
- `latency_ms`: Execution time in milliseconds (specifically measured for `"end"`).
- `idempotency_key`: Key evaluated during idempotency checks.
- `outcome_detail`: Explanatory message.

### Telemetry Grep Recipe
To extract and format telemetry logs from standard outputs:
```bash
grep "JSON_LOG:" stdout.log | sed 's/^JSON_LOG://' | jq .
```
