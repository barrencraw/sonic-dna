# Chain Contract: DNA Batch Parsing Chain

## Overview
The **DNA Batch Parsing Chain** is responsible for reading raw DNA sequence strings, parsing them against JSON rule definitions, updating structured output datasets (JSON and CSV), and recording execution state in a persistent ledger.

---

## 1. Trigger
- **File Watcher**: Triggered when `data/raw/toSequence.txt` contains new non-empty DNA lines (`main.py`).
- **Programmatic Invocation**: Triggered via `run_batch(correlation_id=None)` or `process_once()` CLI entry point.

---

## 2. Inputs
- `data/raw/toSequence.txt`: Raw text input containing one DNA sequence string per line.
- `rules/`: Directory of JSON rule definition files (e.g., `rules_Volume.json`).
- `data/processed_ledger.json`: Persistent ledger storing previously processed idempotency keys and terminal states.

---

## 3. Terminal States
- **`success`**: DNA sequence parsed against valid rules; outputs and ledger entry created.
- **`error`**: DNA sequence parsing failed (e.g. `RuleParseError`); error recorded in ledger and output files.
- **`skipped`**: DNA sequence key was already present in `processed_ledger.json` (deduplicated).
- **`refused`**: Processing aborted due to systemic guard condition (e.g. thermal overload or invalid input).

---

## 4. Invariants
1. **Idempotency**: Re-submitting an already processed DNA sequence produces no duplicate side-effects in output files or ledger.
2. **Atomicity**: Output JSON and CSV files are updated atomically using a staging temporary directory, `flush()` + `fsync()`, and `os.replace()`. Output files are never left in a partial/torn state.
3. **State Consistency**: Outputs and ledger files are saved together if and only if `new_processed_count > 0`.

---

## 5. Error Taxonomy
- `DNAProcessingError` (Base Exception)
  - `RuleLoadError`: Rules folder or definitions failed to load.
  - `InputReadError`: Failed to read input file `toSequence.txt`.
  - `PersistenceError`: Base storage/writing exception.
    - `LedgerLoadError`: Unable to load or parse existing ledger file.
    - `LedgerSaveError`: Failed to save ledger file.
    - `AtomicWriteError`: Failed during temp staging, fsync, or `os.replace` rename of output files.

---

## 6. Idempotency Key
- **Definition**: The raw DNA sequence string (e.g., `VOL08900750712`).
- **Strategy**: Look up the sequence in `data/processed_ledger.json`. If present with a terminal state, log `dedupe_hit=True` and skip re-parsing.

---

## 7. Atomicity Boundary
- Staging directory under `data/output/` created via `tempfile.TemporaryDirectory`.
- Temporary staging files `output.json` and `output.csv` written, flushed, and synced to disk via `os.fsync()`.
- Destination commitment performed via `os.replace(tmp_json, json_output_path)` and `os.replace(tmp_csv, csv_output_path)`.

---

## 8. Required Telemetry & Grep Recipes
### Structured Log Format
Telemetry is emitted as single-line JSON strings prefixed with `JSON_LOG:`:
```json
JSON_LOG:{"timestamp": "2025-06-02T12:00:00Z", "correlation_id": "c123", "actor_id": "batch_parser", "chain_name": "dna_batch_parse", "step": "start|parse|commit|end", "outcome": "success|error|skipped|refused", "latency_ms": 12.5, "idempotency_key": "VOL08900750712", "outcome_detail": {}}
```

### Mandatory Fields
- `timestamp`: UTC ISO 8601 formatted string (`%Y-%m-%dT%H:%M:%SZ`)
- `correlation_id`: Unique trace ID across batch steps
- `actor_id`: Component identity (`batch_parser`, `watcher`, `gui`)
- `chain_name`: `dna_batch_parse`
- `step`: Pipeline stage (`start`, `read_input`, `parse_sequence`, `atomic_write`, `end`)
- `outcome`: Terminal state (`success`, `error`, `skipped`, `refused`)
- `latency_ms`: Execution duration in milliseconds
- `idempotency_key`: DNA sequence string (or `None` for batch summary)
- `outcome_detail`: Context dictionary

### Grep Recipes
- Filter all telemetry logs for DNA batch parsing:
  ```bash
  grep "JSON_LOG:" logs.txt | grep '"chain_name":"dna_batch_parse"'
  ```
- Extract deduplicated/skipped events:
  ```bash
  grep "JSON_LOG:" logs.txt | jq '. | select(.outcome=="skipped")'
  ```
- Extract failures and errors:
  ```bash
  grep "JSON_LOG:" logs.txt | jq '. | select(.outcome=="error" or .outcome=="refused")'
  ```
