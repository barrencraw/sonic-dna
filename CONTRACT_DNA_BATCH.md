# Contract: DNA Batch Parsing

## Trigger
- User manually appends DNA strings to `data/raw/toSequence.txt`.
- Watcher in `main.py` detects changes or `--once` flag is used.

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Idempotency ledger.

## Terminal States
- `SUCCESS`: DNA string parsed and appended to cumulative datasets.
- `ERROR`: Parsing failed; error recorded in datasets.
- `DEDUPE`: DNA string already processed; skipped.
- `NO_NEW_DATA`: Input file empty or all strings already processed.

## Invariants
- **Atomic Multi-File Persistence**: JSON, CSV, and Ledger are updated as a single unit or not at all.
- **Idempotency**: A DNA string is processed and recorded exactly once.
- **Queue Draining**: `toSequence.txt` is cleared only if the batch process completes successfully.

## Observability Contract
- Prefix: `[OBSERVABILITY]`
- Fields: `timestamp` (ISO8601 UTC), `correlation_id`, `actor_id`, `chain`, `step`, `outcome`, `idempotency_key`, `latency_ms`.

## Grep Recipes
- Triage errors: `grep "outcome=error" logs.txt`
- Track a batch: `grep "correlation_id=UUID" logs.txt`
- Dedupe hits: `grep "dedupe_hit=True" logs.txt`
