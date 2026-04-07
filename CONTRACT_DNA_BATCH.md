# Chain Contract: DNA Batch Parsing

## Trigger
- User appends DNA strings to `data/raw/toSequence.txt` while the watcher is running.
- User runs `python3 main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.
- `rules/rules_*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Existing idempotency state.
- `data/output/toSequence_parsed.json`: Existing cumulative results.
- `data/output/toSequence_parsed.csv`: Existing cumulative results.

## Terminal States
- `SUCCESS`: All new DNA strings parsed and appended to JSON/CSV, ledger updated, input file cleared.
- `ERROR`: A critical infrastructure failure (e.g., Disk Full) occurred; no partial updates to output or ledger; input file preserved.
- `SKIPPED`: No new DNA strings found in input file.

## Invariants
- `Idempotency`: A DNA string already in the ledger MUST NOT be added again to JSON or CSV.
- `Atomicity`: Either all output files (JSON, CSV, Ledger) are updated, or none are.
- `Integrity`: JSON and CSV MUST remain consistent with each other.

## Error Classes
- `RuleLoadError`: Rules folder or a specific rule file is missing or malformed.
- `DNAProcessingError`: Generic failure in reading/parsing.
- `PersistenceError`: Failure during atomic write or rename phase.

## Idempotency Key
- The DNA string itself.

## Atomicity Boundary
- The "Commit" phase: `os.replace` calls for the Ledger, JSON, and CSV.

## Required Logs
- `[START] correlation_id={uuid}`
- `[Idempotency] key={dna} dedupe_hit={bool} terminal_outcome={outcome}`
- `[OK] processed={n} Total in ledger={total}`
- `[END] outcome={success/error} latency_ms={ms}`
