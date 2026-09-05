# Chain Contract: DNA Batch Parsing

## Trigger
- File arrival or update in `data/raw/toSequence.txt` (detected by `main.py` watcher loop or executed explicitly via `main.py --once` / `run_batch()`).

## Inputs
- `toSequence.txt`: Raw DNA sequences (one string per line, non-empty, stripped).
- `rules/rules_*.json`: Rule specification schemas used by `DNACalculator`.
- `data/processed_ledger.json`: Structured ledger tracking state and idempotency.

## Terminal States
- `success`: Sequence successfully parsed against rule specifications and saved to outputs.
- `error`: Sequence failed rule parsing (`RuleParseError`); error entry logged in outputs and recorded in ledger.
- `skipped`: Sequence key previously recorded in ledger with terminal status; processing skipped.
- `refused`: Processing rejected due to system invariants (e.g. `ThermalOverloadError` from core heat >= 10.0).

## Invariants
1. **Idempotency**: Processing the same DNA sequence twice results in a deduplication hit (`skipped`) without updating JSON/CSV output files.
2. **Atomicity**: `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv` are written atomically using temporary files and flush/fsync before replacement.
3. **No Silent Drains**: Input file `toSequence.txt` is only cleared by `main.py` if `run_batch()` completes without unhandled errors or thermal refusals.
4. **Thermal Fatigue Limit**: Core heat accumulates at +2.0 units per processed sequence and dissipates at 0.5 units/second. Reaching 10.0 units triggers thermal lockout (`ThermalOverloadError`).

## Error Taxonomy
- `DNAProcessingError`: Base class for processing errors.
  - `InputReadError`: Failure reading input files.
  - `RuleLoadError`: Failure loading rule definitions.
  - `ThermalOverloadError`: System core heat exceeds safety threshold (10.0).
  - `PersistenceError`: Base class for file storage operations.
    - `LedgerLoadError`: Ledger file missing or corrupt JSON.
    - `LedgerSaveError`: Failure writing structured ledger.
    - `AtomicWriteError`: Failure writing output files atomically.

## Idempotency Key Strategy
- Key: Raw stripped DNA sequence string (e.g. `VOL08900750712`).
- Storage: Saved under `"ledger"` key in `data/processed_ledger.json`.

## Atomicity Boundary
- Temporary directory under `data/output/` used to write intermediate files with `os.fsync`.
- Atomic rename (`os.replace`) commits both JSON and CSV files simultaneously.

## Required Logs
All structured logs are emitted to stdout prefixed with `JSON_LOG:` containing:
- `timestamp`: UTC ISO 8601 string (`YYYY-MM-DDTHH:MM:SSZ`)
- `correlation_id`: UUID trace correlation ID
- `actor_id`: ID of the invoking component (e.g. `batch_parser`)
- `chain_name`: `dna_batch_parsing`
- `step`: Lifecycle step name (e.g., `batch_start`, `sequence_parse`, `batch_end`)
- `outcome`: Standardized lowercase status (`success`, `error`, `skipped`, `refused`)
- `latency_ms`: Execution duration in milliseconds
- `idempotency_key`: DNA sequence key
- `outcome_detail`: Contextual diagnostic detail

## Grep Recipes
- View all JSON telemetry logs:
  ```bash
  grep "^JSON_LOG:" app.log
  ```
- Filter for thermal lockout refusals:
  ```bash
  grep '"outcome":"refused"' app.log
  ```
- Trace specific correlation ID:
  ```bash
  grep '"correlation_id":"<YOUR-UUID>"' app.log
  ```
