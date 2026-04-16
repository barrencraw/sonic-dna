# DNA Batch Parsing Chain Contract

## Overview
This contract defines the behavior, invariants, and observability standards for the DNA batch processing chain.

## Chain Details
- **Trigger:** Addition of DNA strings to `data/raw/toSequence.txt` (detected by `main.py` watcher or CLI).
- **Inputs:** A newline-delimited list of DNA strings.
- **Terminal States:**
  - `SUCCESS`: DNA string parsed and added to cumulative datasets.
  - `ERROR`: Parsing or rule validation failure.
  - `SKIPPED`: DNA string already present in `processed_ledger.json`.
  - `NO_NEW_DNA`: Input file empty or all DNA already processed.
  - `START`: Processing loop initiated.
  - `END`: Processing loop completed.
  - `PROCESSING`: DNA string is currently being parsed.

## Invariants (Fatigue System)
- **State:** `system_heat` is persisted in `data/system_state.json`.
- **Heat Gain:** Every successful `Volume` (VOL) DNA parse increases `system_heat` by `amp / 100`.
- **Clarity Penalty:** If `system_heat > 0`, `Clarity` (CLA) DNA parses have their `noise_floor` increased by `int(system_heat)` (making it less negative).
- **Thermal Overload:** If `system_heat > 10.0`, `Clarity` (CLA) DNA parses are refused with a `ThermalOverloadError`.

## Error Classes
- `RuleLoadError`: Failure to load JSON rules from the rules folder.
- `RuleParseError`: DNA string does not match the expected rule structure.
- `ThermalOverloadError`: System heat exceeds safety threshold for the requested operation.
- `PersistenceError`: Atomic write of output files or ledger failed.

## Idempotency
- **Key:** The DNA string itself.
- **Storage:** `data/processed_ledger.json`.

## Atomicity Boundary
- Cumulative JSON, CSV, Ledger, and System State must be updated in a single atomic transaction (via temporary directory and rename) only if at least one new DNA string is processed.

## Observability (log_observability)
Each log entry must include:
- `timestamp`: ISO8601 UTC.
- `correlation_id`: UUID4 for the batch execution.
- `actor_id`: Result of `getpass.getuser()`.
- `chain_name`: "dna_batch_chain".
- `outcome`: One of the Terminal States.
- `idempotency_key`: The DNA string (if applicable).
- `latency_ms`: Duration of the step.

## Telemetry Triage (Grep Recipes)
- Find failures: `grep "outcome=ERROR" observability.log`
- Specific DNA: `grep "idempotency_key=VOL..." observability.log`
- Run summary: `grep "outcome=END" observability.log`
