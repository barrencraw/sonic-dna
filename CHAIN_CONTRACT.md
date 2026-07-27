# DNA Batch Parsing Chain Contract

This document specifies the formal contract for the DNA Batch Parsing chain within SonicDNA.

## 1. Trigger
- Triggered by the file watcher in `main.py` when additions are detected in `data/raw/toSequence.txt`.
- Triggered on-demand via command-line using `python main.py --once`.

## 2. Inputs
- `toSequence.txt`: A text file located at `data/raw/toSequence.txt` containing one DNA sequence string per line.
- `correlation_id` (Optional string): Unique identifier to correlate log messages and actions for a specific batch run.

## 3. Terminal States
- **SUCCESS**: All non-deduplicated DNA strings in the file were processed, results were written atomically to JSON and CSV files, the ledger was updated, and `toSequence.txt` was cleared.
- **ERROR**: An unrecoverable exception occurred (e.g. file I/O failure, rules failing to load). No partial writes are committed, and `toSequence.txt` is NOT cleared.
- **SKIPPED**: No new DNA strings were present in `toSequence.txt`, or all DNA strings were deduplicated using the ledger. Output files were NOT rewritten.
- **REFUSED**: The hardware is in Thermal Lockout state (heat >= 100.0). Sequences are skipped/refused, no partial writes are committed, the ledger persists updated thermal dissipation, and `toSequence.txt` is NOT cleared.

## 4. Invariants
- **No Overwrite on Deduplication**: Any DNA string already existing in the ledger with a terminal outcome (`success` or `error`) must not be re-processed.
- **Output Files Intact**: If no new items are processed (`new_processed_count == 0`), the JSON and CSV output files must not be touched or overwritten.
- **Consistently Formatted Telemetry**: All key events must emit structured JSON logs prefixed with `JSON_LOG:` and use UTC ISO 8601 timestamps (`%Y-%m-%dT%H:%M:%SZ`).

## 5. Error Classes
- `DNAProcessingError`: Generic base exception for DNA batch processing errors.
- `RuleLoadError`: Raised when the JSON rule configurations cannot be loaded from the `rules/` directory.
- `PersistenceError`: Raised when atomic writing of JSON/CSV output files or saving the ledger fails.
- `ThermalOverloadError`: Raised when system heat >= 100.0.

## 6. Idempotency Key
- The DNA sequence string itself serves as the idempotency key.
- Terminal outcomes (`success` and `error`) are registered in `processed_ledger.json` under this key.

## 7. Atomicity Boundary
- All output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) must be written atomically using a temporary file write-flush-sync-rename sequence on the same filesystem.
- The ledger file (`processed_ledger.json`) must be saved atomically in a similar fashion.
- Truncating `toSequence.txt` only happens after the batch parser completes successfully.

## 8. Required Logs
Structured JSON logs must contain the following fields:
- `timestamp`: UTC ISO 8601 formatted string (`%Y-%m-%dT%H:%M:%SZ`).
- `correlation_id`: String (UUID or N/A).
- `actor_id`: String ("system" or "orchestrator").
- `chain_name`: String ("dna_batch_parsing").
- `step`: String representing the step (`start`, `deduplicate`, `process_sequence`, `thermal_lockout_check`, `apply_thermal_consequence`, `save_ledger`, `commit_files`, `end`).
- `outcome`: String matching the lowercase enum (`success`, `error`, `skipped`, `refused`).
- `latency_ms`: Integer or null.
- `idempotency_key`: DNA sequence string or null.
- `outcome_detail`: Descriptive message string.
