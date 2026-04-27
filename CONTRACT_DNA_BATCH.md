# Chain Contract: DNA Batch Parsing

## Overview
This chain handles the batch processing of DNA strings from `toSequence.txt`, converting them into structured JSON and CSV formats while maintaining an idempotency ledger and a thermal stress (Fatigue) system.

## Contract
- **Trigger**: New non-empty lines detected in `data/raw/toSequence.txt`.
- **Inputs**:
  - `dna_list`: A list of DNA strings.
- **Terminal States**:
  - `SUCCESS`: All processed strings were successfully parsed.
  - `PARTIAL_SUCCESS`: Some strings were successfully parsed, others resulted in errors.
  - `ERROR`: All processed strings resulted in errors.
  - `NO_NEW_DNA`: No strings were processed (all were deduplicated).
- **Invariants**:
  - `system_heat` must always be $\ge$ 0.0.
  - `Clarity` (CLA) DNA parsing is refused if `system_heat` > 10.0.
  - The Idempotency Ledger, JSON output, and CSV output must be updated atomically.
- **Error Classes**:
  - `DNAProcessingError`: Base class for processing failures.
  - `RuleLoadError`: Rules folder or files cannot be loaded.
  - `PersistenceError`: Failed to write output files atomically.
  - `ThermalOverloadError`: Operation refused due to high system heat.
- **Idempotency**:
  - **Key**: The raw DNA string (e.g., `VOL08900750712`).
  - **Ledger**: `data/processed_ledger.json`.
- **Atomicity Boundary**:
  - The commitment of JSON, CSV, and the Ledger happens as a single transaction using `os.replace` from a temporary directory.

## Telemetry & Grep Recipes
All logs follow the format: `| TELEMETRY | {"correlation_id": "...", "step": "...", "outcome": "...", ...}`

### Triage Recipes
- **Find all errors in a batch**:
  `grep "| TELEMETRY |" | grep "ERROR" | grep "<correlation_id>"`
- **Check batch completion status**:
  `grep "| TELEMETRY |" | grep "BATCH_END"`
- **Monitor system heat changes**:
  `grep "system_heat" data/system_state.json` (Current state)
  `grep "| TELEMETRY |" | grep "CONSEQUENCE_APPLIED"` (Penalty logs)
