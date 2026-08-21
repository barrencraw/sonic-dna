# Chain Contract: DNA Batch Parsing Chain

## Trigger
- **Watcher**: Background thread in `main.py` monitoring `data/raw/toSequence.txt`.
- **CLI**: One-time execution via `python3 main.py --once`.
- **Programmatic**: Direct call to `utils.dna_ui.run_batch(correlation_id=...)`.

## Inputs
- File: `data/raw/toSequence.txt` containing line-separated raw DNA sequences (e.g., `VOL08900750712`).

## Terminal States
Standardized lowercase values defined by `DNAStatus`:
- `success`: DNA sequence successfully parsed against matching variable rule.
- `error`: Invalid prefix or schema parsing failure recorded as error entry.
- `skipped`: Sequence already processed with a terminal outcome in ledger.
- `refused`: Processing rejected due to Thermal Fatigue Lockout (core heat >= 10.0).

## Invariants
1. **Idempotency**: Sequences with terminal outcomes (`success`, `error`) in `processed_ledger.json` are skipped and not re-processed.
2. **Atomicity**: Output files (`data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`) and `data/processed_ledger.json` are written using temporary file handles with `flush()` and `os.fsync()`, then atomically replaced using `os.replace()`. Disk/write failures leave previous state untouched.
3. **Thermal Fatigue Safety**:
   - Each parsed sequence accumulates +2.0 heat units.
   - Core heat dissipates at 0.5 heat units per second based on UTC ISO 8601 timestamps (`%Y-%m-%dT%H:%M:%SZ`).
   - If core heat >= 10.0, the system refuses execution, logs a refusal telemetry record, and raises `ThermalOverloadError("Thermal Lockout")`.
   - `main.py` catches `DNAProcessingError` and preserves `toSequence.txt` without clearing it.

## Error Taxonomy
- `DNAProcessingError` (Base exception)
  - `InputReadError`: Raised when reading input DNA file fails.
  - `RuleLoadError`: Raised when rule JSON definitions cannot be loaded.
  - `PersistenceError` (Base persistence failure)
    - `LedgerLoadError`: Raised when ledger file exists but is corrupted.
    - `LedgerSaveError`: Raised when ledger cannot be saved atomically.
    - `AtomicWriteError`: Raised when writing/replacing output files fails.
  - `ThermalOverloadError`: Raised on thermal fatigue lockout.

## Idempotency Key Strategy
- The raw trimmed string `dna_sequence` serves as the unique idempotency key.

## Atomicity Boundary
- Outputs: `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`.
- Persistence: `data/processed_ledger.json`.

## Required Telemetry Logs
Every sequence step emits a single-line JSON payload prefixed with `JSON_LOG:` containing:
- `timestamp`: UTC ISO 8601 timestamp (`%Y-%m-%dT%H:%M:%SZ`).
- `correlation_id`: Trace correlation UUID string.
- `actor_id`: `batch_parser`.
- `chain_name`: `dna_batch_parser`.
- `step`: `parse_sequence`.
- `outcome`: `success` | `error` | `skipped` | `refused`.
- `latency_ms`: Duration of execution in milliseconds.
- `idempotency_key`: `dna_sequence` value.
- `outcome_detail`: Context detail or error message string.

## Grep Recipes
- View all structured telemetry:
  ```bash
  grep "JSON_LOG:" app.log
  ```
- Filter skipped idempotency hits:
  ```bash
  grep "JSON_LOG:" app.log | grep '"outcome": "skipped"'
  ```
- Filter thermal lockout refusals:
  ```bash
  grep "Thermal Lockout" app.log
  ```
- Inspect ledger terminal outcomes:
  ```bash
  grep "terminal_outcome" data/processed_ledger.json
  ```
