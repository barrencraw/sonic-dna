# Chain Contract: DNA Batch Parsing

## Overview
The DNA Batch Parsing chain is responsible for reading raw DNA sequences from `data/raw/toSequence.txt`, parsing them against rules defined in `rules/`, recording execution results in `data/processed_ledger.json`, and writing structured JSON and CSV outputs atomically to `data/output/`.

---

## Contract Specification

### 1. Trigger
- Manual CLI / programmatic invocation of `run_batch(correlation_id=None, actor_id='batch_parser')`.
- Continuous background watcher in `main.py` monitoring `data/raw/toSequence.txt`.

### 2. Inputs
- `data/raw/toSequence.txt`: Raw text file containing one DNA sequence per line.
- `rules/*.json`: Variable parsing rulesets.
- `data/processed_ledger.json`: Persistent idempotency ledger tracking processed DNA sequences.

### 3. Terminal States
The terminal states for each DNA sequence execution outcome are represented in lowercase:
- `success`: DNA sequence successfully parsed and appended to JSON/CSV data output.
- `error`: DNA sequence failed parsing against active rulesets; error details captured.
- `skipped`: DNA sequence previously processed and deduplicated via idempotency key in ledger.
- `refused`: Processing refused due to system bounds or lockouts (e.g. thermal fatigue).

### 4. Invariants
- **Deduplication:** A DNA sequence previously recorded in the ledger with a terminal outcome (`success` or `error`) is skipped on subsequent invocations without duplicate entries or side effects.
- **Atomicity:** File operations on `toSequence_parsed.json` and `toSequence_parsed.csv` use temporary files in the target directory, flushed with `flush()` and committed with `fsync()` before atomic swap via `os.replace()`. Output files are rewritten only if `new_processed_count > 0`.
- **Persistence Safety:** On exception during batch processing, input file `toSequence.txt` is NOT cleared, preserving raw data for retry or investigation.

### 5. Error Taxonomy
- `DNAProcessingError` (base exception)
  - `InputReadError`: Failure while reading raw input files.
  - `RuleLoadError`: Failure while loading rule configurations from disk.
- `PersistenceError` (base exception)
  - `LedgerLoadError`: Failure while loading or parsing existing ledger data.
  - `LedgerSaveError`: Failure while serializing or persisting ledger updates.
  - `AtomicWriteError`: Failure during temporary file write, sync, or atomic replace operation.

### 6. Idempotency Key Strategy
- **Key Format:** The raw DNA sequence string (e.g., `VOL08900750712`).
- **Storage:** Stored in `data/processed_ledger.json` under `ledger[idempotency_key]`.

### 7. Atomicity Boundary
- **Boundary:** Creation of temporary directory `tmp_dir` within `data/output/`.
- **Commit Phase:** Flushed to disk handle (`jf.flush()`), synced (`os.fsync(jf.fileno())`), then replaced (`os.replace(tmp_path, target_path)`).

### 8. Required Telemetry Logs
Structured telemetry logs are emitted via `log_structured` prefixed with `JSON_LOG:` with mandatory schema:
- `timestamp`: UTC ISO 8601 string.
- `correlation_id`: Unique trace ID or generated UUID.
- `actor_id`: Entity triggering action (`batch_parser`, `watcher`, or user ID).
- `chain_name`: `dna_batch_parsing`.
- `step`: Process step (`start`, `parse_sequence`, `commit_outputs`, `end`).
- `outcome`: `success`, `error`, `skipped`, or `refused`.
- `latency_ms`: Execution duration in milliseconds.
- `idempotency_key`: DNA sequence string (where applicable).
- `outcome_detail`: Detailed message or error string.

---

## Grep Recipes

```bash
# Filter all structured JSON telemetry logs
grep "JSON_LOG:" app.log

# Track specific DNA sequence idempotency key execution
grep "idempotency_key" app.log

# Inspect batch parsing errors
grep "DNAProcessingError" app.log
```
