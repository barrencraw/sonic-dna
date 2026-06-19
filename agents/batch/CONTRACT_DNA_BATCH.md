# DNA Batch Parsing Chain Contract

## Chain Definition
- **Name:** DNA Batch Parsing
- **Trigger:** File watcher on `data/raw/toSequence.txt` or manual `--once` invocation via `main.py`.
- **Inputs:** A text file containing one DNA sequence per line.
- **Outputs:**
  - `data/output/toSequence_parsed.json` (Cumulative JSON)
  - `data/output/toSequence_parsed.csv` (Cumulative CSV)
  - `data/processed_ledger.json` (Idempotency and State Ledger)

## Terminal States (DNAStatus)
- **success**: Sequence parsed correctly and recorded.
- **error**: Sequence failed validation/parsing; error recorded.
- **skipped**: Sequence already processed (idempotency hit).
- **processing**: Initial state before terminal outcome.

## Invariants
1. **Atomicity**: The update to the ledger and the persistence of results to JSON/CSV must be atomic. If any write fails, none of the changes should be visible to other processes.
2. **Idempotency**: Processing the same DNA sequence multiple times must result in exactly one entry in the output files.
3. **Thermal Safety**: The system implements a thermal fatigue axis.
   - `MAX_HEAT = 10.0`
   - `HEAT_PER_ITEM = 1.0`
   - `COOLING_RATE_PER_SEC = 0.01`
   - If `system_heat` reaches `MAX_HEAT`, the batch must be refused with `ThermalOverloadError`.
4. **Consistency**: JSON and CSV outputs must contain the same data.

## Error Classes
- `DNAProcessingError`: Base class.
- `RuleParseError`: Raised when a DNA string does not match any known rule.
- `PersistenceError`: Raised when atomic write or rename fails.
- `ThermalOverloadError`: Raised when the system exceeds its heat capacity.

## Telemetry
- All logs must use the `JSON_LOG: ` prefix followed by a JSON object.
- Fields: `timestamp`, `correlation_id`, `chain_name`, `step`, `outcome`, `actor_id`, `latency_ms`.
- Step names: `batch_start`, `item_process`, `batch_end`.
