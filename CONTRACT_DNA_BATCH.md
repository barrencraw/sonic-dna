# Chain Contract: DNA Batch Parsing

## Trigger
- Background watcher detects changes in `data/raw/toSequence.txt`.
- Manual execution via `python main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: A file containing one DNA string per line.
- `rules/*.json`: Rule definition files for parsing.
- `data/system_state.json`: Current system state, including `system_heat`.

## Terminal States
- `SUCCESS`: All new DNA strings processed successfully.
- `PARTIAL_SUCCESS`: Some DNA strings processed, some failed.
- `ERROR`: Critical failure (e.g., IO error, rule load error).
- `NO_NEW_DNA`: No new DNA strings to process (all deduplicated).
- `SKIPPED`: All strings in batch skipped due to idempotency or refusal.

## Invariants
- **Idempotency**: A DNA string already present in `processed_ledger.json` with a successful outcome is not re-processed.
- **Atomicity**: `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` are updated together. If one fails, none should be committed.
- **Deduplication**: Identical strings within the same batch are processed only once.
- **Fatigue**: `system_heat` increases with Volume (VOL) processing and decays over time (batch start). Clarity (CLA) is penalized or refused if heat is high.

## Error Classes
- `RuleLoadError`: Failed to load or parse rule JSONs.
- `RuleParseError`: DNA string does not match any rule or is malformed.
- `PersistenceError`: Failed to write output files atomically.
- `ThermalOverloadError`: DNA string (e.g., CLA) refused due to high `system_heat`.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- All output files are staged in a temporary directory and moved to `data/output/` and `data/` using `os.replace`.
- `toSequence.txt` is cleared only after successful output commitment.

## Required Logs (Structured)
Format: `timestamp | correlation_id | chain_name | step | outcome | latency_ms | actor_id | idempotency_key | [message]`

### Grep Recipes
- `grep "| ERROR |" observability.log` (Find all failures)
- `grep "VOL08900750712" observability.log` (Trace specific DNA)
- `grep "| COMMIT |" observability.log` (Check batch completions)
- `grep "Outcome.SUCCESS" observability.log` (Find successes)
