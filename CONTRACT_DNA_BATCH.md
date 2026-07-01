# Chain Contract: DNA Batch Parsing

## Trigger
- `utils.dna_ui.main(correlation_id, actor_id)`
- Background watcher in `main.py`
- One-time runner: `python main.py --once`

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.
- `rules/*.json`: Rule definitions for the `DNACalculator`.

## Terminal States
- `SUCCESS`: DNA parsed correctly and added to output.
- `ERROR`: DNA failed parsing (recorded with error detail).
- `SKIPPED`: DNA already exists in ledger with `SUCCESS` (idempotency hit).
- `REFUSED`: System refused to process (e.g., thermal lockout - reserved for future).

## Invariants
- **Atomicity**: The output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and the `processed_ledger.json` are updated as a single atomic unit. If any write fails, none are committed.
- **Idempotency**: Successful items are never re-processed.
- **Input Integrity**: The input file `toSequence.txt` is only cleared if the entire batch persistence succeeds.

## Error Classes
- `RuleLoadError`: Critical failure to load rules.
- `PersistenceError`: Critical failure during atomic file write.
- `DNAProcessingError`: Generic base for processing failures.

## Telemetry
- `JSON_LOG:` prefixed structured logs.
- Fields: `timestamp`, `level`, `step`, `correlation_id`, `idempotency_key`, `outcome`, `latency_ms`, `error_detail`.

## Grep Recipe
```bash
grep 'JSON_LOG:' | sed 's/JSON_LOG: //' | jq '.'
```
