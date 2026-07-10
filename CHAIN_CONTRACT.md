# Chain Contract: DNA Batch Parsing

## Triggers
- **Watcher:** Triggered by file modification in `data/raw/toSequence.txt`.
- **Manual CLI:** Triggered by `python main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA string per line.
- `rules/*.json`: Rule definition files for parsing.

## Terminal States
- `SUCCESS`: DNA string parsed and appended to cumulative JSON/CSV.
- `ERROR`: DNA string failed to parse; error recorded in cumulative JSON/CSV.
- `SKIPPED`: DNA string already exists in ledger with a terminal state (Idempotency).
- `REFUSED`: Processing stopped due to thermal fatigue (Lockout).

## Invariants
- **No Silent Drains:** Input file is only cleared if the batch processor successfully commits its changes.
- **Atomic Commits:** Ledger, JSON, and CSV outputs are updated as a single logical unit using atomic renames.
- **Idempotency:** A DNA string with a terminal outcome in the ledger is never re-processed.
- **Thermal Safety:** System refuses processing if heat exceeds `MAX_HEAT`.

## Error Classes
- `RuleParseError`: Malformed DNA string relative to rules.
- `RuleLoadError`: Missing or invalid rule JSON files.
- `PersistenceError`: Failure to write or rename output files atomically.
- `ThermalOverloadError`: System-induced lockout due to excessive processing.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- The scope includes updating `processed_ledger.json`, `toSequence_parsed.json`, and `toSequence_parsed.csv`.

## Required Logs (JSON_LOG:)
- `timestamp` (ISO 8601 UTC)
- `correlation_id` (UUID)
- `actor_id` (system/user)
- `chain_name` ("dna_batch_parsing")
- `step` (e.g., "start", "parse", "persist", "end")
- `outcome` (e.g., "success", "error", "refused")
- `idempotency_key` (if applicable)
- `latency_ms`

## Telemetry Grep Recipe
```bash
grep "JSON_LOG:" logs/*.log | jq '. | select(.chain_name == "dna_batch_parsing")'
```
