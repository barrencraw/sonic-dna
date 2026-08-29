# Chain Contract: DNA Batch Parsing Chain

## Overview
This document specifies the contract governing the DNA Batch Parsing chain.

## 1. Trigger
- Direct invocation via `utils.dna_ui.run_batch()` or `main.py --once`.
- Background directory monitoring via `watch_loop()` in `main.py` detecting new non-empty sequences in `data/raw/toSequence.txt`.

## 2. Inputs
- `input_file`: `data/raw/toSequence.txt` containing line-delimited DNA sequences.
- `rules_folder`: `rules/` containing variable JSON schema rules.
- `ledger_file`: `data/processed_ledger.json` recording state and processed idempotency keys.

## 3. Terminal States
- `success`: DNA sequence successfully parsed and persisted.
- `error`: Rule parse error recorded; execution continues.
- `skipped`: Idempotency key match in ledger; duplicate processing avoided.
- `refused`: Thermal overload threshold reached (10.0 heat units); batch execution halted with `ThermalOverloadError`.

## 4. Invariants
- **Atomicity Boundary**: Both output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) are written atomically using temporary directory flush/sync and `os.replace()`.
- **Idempotency**: Identical DNA sequence inputs with terminal outcomes ('success' or 'error') are deduplicated without re-execution or side effects.
- **No Silent Drains**: Input file `data/raw/toSequence.txt` is cleared ONLY upon successful batch processing without thermal overload.
- **Thermal Fatigue Axis**: Each successful parse adds 2.0 heat units. System cools down at 0.5 units/sec in UTC. Safety lockout threshold is 10.0 heat units.
- **Backward Compatibility**: Ledger and output files support both legacy flat structures and modern structured layouts (`dna` and `dna_sequence` fields).

## 5. Error Taxonomy
- `DNAProcessingError` (Base Exception)
  - `RuleLoadError`: Rules missing or corrupted.
  - `InputReadError`: Input file read failure.
  - `ThermalOverloadError`: System core heat exceeds safety lockout (10.0 units).
  - `PersistenceError` (Base I/O Exception)
    - `LedgerLoadError`: Ledger JSON corrupted.
    - `LedgerSaveError`: Ledger write failure.
    - `AtomicWriteError`: Temp file creation/rename failure during atomic write.

## 6. Required Logs & Telemetry
Every step emits a structured JSON line prefixed with `JSON_LOG:` with standard fields:
- `timestamp`: UTC ISO 8601 string (`%Y-%m-%dT%H:%M:%SZ`)
- `correlation_id`: Trace UUID string
- `actor_id`: `batch_parser`
- `chain_name`: `dna_batch_parsing`
- `step`: Operation step (`start`, `load_rules`, `thermal_check`, `dedupe_check`, `parse_sequence`, `process_sequence`, `end`)
- `outcome`: Lowercase string enum `DNAStatus` (`success`, `error`, `skipped`, `refused`)
- `latency_ms`: Execution duration in milliseconds
- `idempotency_key`: DNA sequence string (when applicable)
- `outcome_detail`: Structured dictionary or context message

## 7. Grep Recipes
- Search all telemetry JSON logs:
  `grep "JSON_LOG:" app.log`
- Search thermal lockouts or refusals:
  `grep "JSON_LOG:" app.log | grep '"outcome": "refused"'`
- Filter by specific correlation ID:
  `grep "JSON_LOG:" app.log | grep '"correlation_id": "<uuid>"'`
