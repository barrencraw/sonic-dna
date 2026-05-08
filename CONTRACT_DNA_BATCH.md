# Chain Contract: DNA Batch Processing (dna_batch_chain)

## Trigger
- Background watcher detects new non-empty content in `data/raw/toSequence.txt`.
- Manual invocation via `python main.py --once`.

## Inputs
- `dna_list`: List of raw DNA strings (e.g., `VOL08900750712`).
- `system_state.json`: Persistent state containing `system_heat`.

## Terminal States (Outcome Enum)
- `START`: Batch processing initiated.
- `END`: Batch processing completed (logged with final outcome).
- `SUCCESS`: Individual DNA string parsed and recorded.
- `ERROR`: Individual DNA string failed parsing or system-level error.
- `SKIPPED`: DNA string already present in ledger (idempotency hit).

## Invariants
- **Idempotency**: Processing the same DNA string multiple times must not result in duplicate entries in the output files.
- **Atomicity**: The output JSON, CSV, and the `processed_ledger.json` must be updated as a single logical transaction.
- **Thermal Integrity**: `system_heat` must be persisted and affects DNA processing (Fatigue/Noise). Passive dissipation of 0.5 units occurs per batch.

## Error Classes
- `DNAProcessingError`: Base class.
- `RuleLoadError`: Failure to load rule JSONs.
- `RuleParseError`: Malformed DNA string.
- `PersistenceError`: Failure to write or move output files.
- `ThermalOverloadError`: `system_heat` exceeds 10.0 (Refusal).

## Idempotency Key
- The raw DNA string itself.

## Atomicity Boundary
- Files: `toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`.
- Pattern: Temp directory + `os.replace`.

## Required Logs (Telemetry)
- Each log must contain: `timestamp`, `correlation_id` (UUID), `chain_name` ("dna_batch_chain"), `step`, `outcome`, `actor_id` ("jules"), and `latency_ms` (for END).

## Grep Recipe
```bash
grep "| TELEMETRY |" <log_file> | jq '.data'
```
