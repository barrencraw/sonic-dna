# DNA Batch Parsing Chain Contract

## Overview
The DNA Batch Parsing chain monitors, processes, and persists Sonic DNA sequences from raw input into structured JSON and CSV outputs.

## Chain Contract Specifications

### Trigger
- Continuous background directory watch loop or single batch invocation (`--once`).
- Monitors `data/raw/toSequence.txt`.

### Inputs
- File: `data/raw/toSequence.txt` containing one DNA sequence per line.
- Operational parameters: `correlation_id` (UUID trace identifier), `actor_id` (defaults to `"batch_parser"`).

### Terminal States
- `success`: DNA sequence parsed successfully and results persisted.
- `error`: DNA sequence failed schema or rule validation; recorded with error details.
- `skipped`: DNA sequence deduplicated via idempotency key in ledger, or missing input file.
- `refused`: Execution halted due to Thermal Lockout safety threshold violation (core heat >= 10.0 units).

### Invariants
1. **Idempotency**: A DNA sequence processed previously (outcome `success`, `error`, `skipped`, or `refused`) is never re-parsed.
2. **Atomicity**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are written atomically using temporary directory flushes, fsyncs, and atomic replacements.
3. **No Silent Drains**: When `ThermalOverloadError` is raised, input files are not cleared by `main.py`, preserving unprocessed data.

### Error Taxonomy
- `DNAProcessingError` (Base Exception)
  - `InputReadError`: Failure reading raw input file.
  - `RuleLoadError`: Failure reading or parsing rule configuration JSON files.
  - `PersistenceError` (Base Persistence Exception)
    - `LedgerLoadError`: Corrupted JSON or unreadable ledger file.
    - `LedgerSaveError`: Failure writing updated ledger file.
    - `AtomicWriteError`: Failure flushing, syncing, or replacing output files.
  - `ThermalOverloadError`: System thermal lockout threshold (>= 10.0 core heat units) exceeded.

### Idempotency Key Strategy
- `idempotency_key = dna_sequence` (the raw DNA sequence string).

### Atomicity Boundary
- All output commits (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`) occur within a single atomic directory swap (`tempfile.TemporaryDirectory`, `os.fsync`, `os.replace`).

### Required Logs & Telemetry
Every step and terminal state emits structured JSON telemetry prefixed with `JSON_LOG:`:
- Fields: `timestamp` (UTC ISO 8601 `YYYY-MM-DDTHH:MM:SSZ`), `correlation_id`, `actor_id`, `chain_name` (`dna_batch_parser`), `step`, `outcome`, `latency_ms`, `idempotency_key`, `outcome_detail`.

### Grep Recipes
- View all structured telemetry logs:
  `grep "JSON_LOG:" app.log`
- View terminal outcomes:
  `grep "JSON_LOG:" app.log | grep '"step": "process_sequence"'`
- View thermal lockouts / refusals:
  `grep "JSON_LOG:" app.log | grep '"outcome": "refused"'`
