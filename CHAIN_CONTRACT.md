# DNA Batch Processing Chain Contract

## Triggers
- **Watcher**: Triggered by new content in `data/raw/toSequence.txt`.
- **Once-Runner**: Triggered by `--once` CLI flag.

## Inputs
- `toSequence.txt`: One or more DNA sequences (e.g., `VOL08900750712`), one per line.

## Terminal States
- `SUCCESS`: Sequence parsed and committed to output.
- `ERROR`: Sequence failed parsing (recorded in output with error message).
- `SKIPPED`: Sequence already exists in ledger with terminal outcome.
- `REFUSED`: Sequence blocked by Thermal Lockout (overheat).

## Invariants
- **Atomic Commit**: JSON, CSV, and Ledger are updated as a single logical unit.
- **Idempotency**: Identical DNA sequences are not re-processed once a terminal outcome is reached.
- **Thermal Safety**: Heat must never exceed `MAX_HEAT` (100.0).

## Error Classes
- `RuleLoadError`: Rules folder missing or corrupted.
- `DNAProcessingError`: IO failure or systemic issue.
- `ThermalOverloadError`: System hit thermal lockout.
- `PersistenceError`: Atomic write failed.

## Telemetry
- `JSON_LOG:` prefix for all structured logs.
- Mandatory fields: `timestamp`, `correlation_id`, `actor_id`, `chain_name`, `step`, `outcome`, `latency_ms`, `idempotency_key`.

## Grep Recipe
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG://' | jq .
```
To filter by correlation ID:
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG://' | jq 'select(.correlation_id == "YOUR-ID")'
```
