# Chain Contract: DNA Batch Parsing

## Win Condition
Hardened DNA Batch Parsing with Thermal Fatigue and Structured Logging.

**Done when:**
- Batch processor implements Thermal Fatigue (heat accumulation/dissipation).
- All terminal outcomes use standardized JSON logging with correlation IDs.
- Idempotency bug in the main processing loop is fixed.
- Main entry point supports external correlation IDs and handles thermal lockout.
- Test suite verifies thermal behavior and log structure.

## Contract

| Property | Definition |
| :--- | :--- |
| **Trigger** | File watcher detected change in `toSequence.txt` or manual `--once` CLI flag. |
| **Inputs** | `data/raw/toSequence.txt` (DNA strings), `data/processed_ledger.json` (state). |
| **Terminal States** | `SUCCESS`, `ERROR`, `SKIPPED`, `REFUSED` (Thermal lockout). |
| **Invariants** | Output files (JSON/CSV) must be consistent; Ledger must reflect physical disk state. |
| **Error Classes** | `RuleParseError`, `RuleLoadError`, `PersistenceError`, `ThermalOverloadError`. |
| **Idempotency Key** | DNA String (e.g., `VOL08900750712`). |
| **Atomicity Boundary** | Single batch run (Atomic Rename of temporary output directory). |
| **Required Logs** | `JSON_LOG:` prefixed entries with `timestamp`, `correlation_id`, `outcome`, `latency_ms`. |

## Thermal Parameters
- `MAX_HEAT`: 100.0
- `HEAT_PER_SEQ`: 20.0
- `COOLING_RATE`: 2.0 units/sec
- `LOCKOUT_MSG`: "Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines."
