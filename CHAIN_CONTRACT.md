# Chain Contract: DNA Batch Parsing

This contract defines the execution rules, constraints, error handling, and telemetry requirements for the DNA Batch Parsing chain in SonicDNA.

## 1. Specification

| Property | Definition |
| :--- | :--- |
| **Trigger** | Appended or new DNA strings detected in `data/raw/toSequence.txt` by the watcher loop or run manually with the `--once` CLI flag. |
| **Inputs** | Raw DNA sequence strings (stripped, non-empty, unique lines). |
| **Terminal States** | `SUCCESS` (when new DNA strings are successfully parsed and saved) or `NO_NEW_ITEMS` (when all inputs are duplicates/deduplicated). |
| **Invariants** | 1. Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) are modified/rewritten only if `new_processed_count > 0`. <br> 2. The processed ledger is updated atomically and persistently for every newly processed item. <br> 3. No duplicate entries or processed outputs are created for any already completed sequence (idempotency). |
| **Error Classes** | - `DNAProcessingError` (Base class)<br> - `InputReadError` (Raised when reading input files fails)<br> - `PersistenceError` (Base class for persistence errors)<br> - `LedgerSaveError` (Raised on ledger write failures)<br> - `AtomicWriteError` (Raised on output JSON/CSV write failures) |
| **Idempotency Key** | The raw `dna_sequence` string itself. |
| **Atomicity Boundary** | Output JSON/CSV files and the processed ledger are written to temporary files, flushed, synced (via `fsync`), and atomically renamed (via `os.replace`) to ensure they are never partially written or corrupted in a crash. |

---

## 2. Telemetry Requirements

All core processing steps and outcomes must emit standard structured logs prefixed with `JSON_LOG:` in standardized JSON format with the following mandatory fields:

- `timestamp` (UTC, ISO-8601 formatted, e.g., `YYYY-MM-DDTHH:MM:SSZ`)
- `correlation_id` (Unique identifier passed from presenter or "N/A")
- `actor_id` ("system" or user id)
- `chain_name` ("dna_batch_parsing")
- `step` (e.g., `"start"`, `"parse_sequence"`, `"write_output"`, `"completed"`, `"cleanup_failure"`)
- `outcome` (lowercase `DNAStatus` enum, e.g., `"success"`, `"error"`, `"skipped"`, `"refused"`)
- `latency_ms` (integer)
- `idempotency_key` (the DNA sequence or "N/A")
- `outcome_detail` (detailed description or exception message)

### Grep Telemetry Recipe

To extract and inspect the structured logs:
```bash
grep "JSON_LOG:" stdout.log | sed 's/JSON_LOG://g' | jq .
```
