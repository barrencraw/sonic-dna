# Chain Contract: DNA Batch Processing

## Overview
This chain handles batch parsing of DNA strings from an input file, applying rules, managing system thermal state (Fatigue), and persisting results with idempotency and atomicity.

## Trigger
- Execution of `utils/dna_ui.py`'s `main()` function, typically via `main.py` watcher or `--once` flag.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA string per line.
- `data/processed_ledger.json`: Persistent record of previously processed DNA strings.
- `data/system_state.json`: Persistent record of system heat/fatigue.

## Terminal States
- `SUCCESS`: All new DNA strings processed successfully.
- `ERROR`: A critical failure occurred (e.g., IO error, rule load failure).
- `SKIPPED`: All input DNA strings were already in the ledger.
- `NO_NEW_DNA`: Input file was empty or missing.
- `PARTIAL_SUCCESS`: Some DNA strings succeeded while others failed or were refused.

## Invariants
- **Idempotency**: A DNA string present in the ledger must not be re-parsed.
- **Atomicity**: Updates to `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` must occur as a single commit using the atomic rename pattern.
- **Thermal Determinism**: Heat gain/loss follows fixed formulas (`amp / 100` gain for Volume, `-1.0` natural cooling per batch).
- **Fatigue Impact**: Clarity DNA parsing must be penalized or refused based on `system_heat` thresholds.

## Error Classes
- `DNAProcessingError`: Base class for errors in this chain.
- `RuleLoadError`: Rules folder missing or corrupted.
- `PersistenceError`: Failed to write output files atomically.
- `ThermalOverloadError`: Heat exceeds threshold (10.0) for sensitive operations (Clarity).

## Idempotency Key
- The raw DNA string.

## Atomicity Boundary
- Staging of all output files in a `tempfile.TemporaryDirectory` followed by `os.replace` for each.

## Required Logs
- Structured logs via `log_observability`:
  - `timestamp`: ISO8601 UTC.
  - `correlation_id`: UUID4 for the batch run.
  - `chain_name`: "dna_batch_chain".
  - `step`: "START", "ITEM_PROCESS", "END".
  - `outcome`: From `Outcome` Enum.
  - `latency_ms`: Duration of the step or batch.
  - `actor_id`: System user.
  - `idempotency_key`: DNA string (for item logs).

## Grep Recipes for Telemetry Triage
- `grep "outcome=ERROR" logs.txt`: Find critical failures.
- `grep "dedupe_hit=True" logs.txt`: Verify idempotency hits.
- `grep "system_heat" data/system_state.json`: Check current thermal stress.
