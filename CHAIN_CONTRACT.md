# DNA Batch Parsing Chain Contract

## Trigger
- **Watcher**: Continuously monitors `data/raw/toSequence.txt` for content changes.
- **CLI**: Manual invocation via `main.py --once`.

## Inputs
- DNA strings (one per line) from `data/raw/toSequence.txt`.

## Terminal States
- `SUCCESS`: Sequence parsed and committed to JSON/CSV/Ledger.
- `ERROR`: Sequence failed to parse; error recorded in JSON/CSV/Ledger.
- `SKIPPED`: Sequence already exists in the ledger with a terminal outcome.

## Invariants
- **Consistency**: The `processed_ledger.json`, `toSequence_parsed.json`, and `toSequence_parsed.csv` must always be updated as a single atomic unit.
- **Idempotency**: A DNA string with a terminal outcome in the ledger must never be re-processed.

## Error Classes
- `RuleLoadError`: Critical failure to initialize `DNACalculator`.
- `DNAProcessingError`: Generic failure during file read/write.
- `PersistenceError`: Atomic commit failure (temporary file or rename error).
- `RuleParseError`: Individual sequence parsing failure (non-critical, recorded as `error` outcome).

## Idempotency Key
- The raw DNA string.

## Atomicity Boundary
- Files: `data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`, `data/processed_ledger.json`.
- Pattern: Multi-file atomic rename using a temporary directory on the same mount point.

## Required Logs (Structured)
- Prefix: `JSON_LOG:`
- Mandatory Fields: `timestamp` (ISO 8601 UTC), `correlation_id`, `actor_id`, `chain_name`, `step`, `outcome`.
- Optional Fields: `latency_ms`, `idempotency_key`, `outcome_detail`.

### Grep Recipe
```bash
grep "JSON_LOG:" stdout.log | jq .
```
