# Chain Contract: DNA Batch Parsing

## Trigger
- Explicit invocation of `utils.dna_ui.main()` (batch mode).
- Background watcher detecting changes in `data/raw/toSequence.txt`.

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.
- `rules/*.json`: Rule definitions for various DNA types.
- `data/processed_ledger.json`: Persistence for idempotency.

## Terminal States
- `SUCCESS`: All new DNA strings parsed and recorded.
- `NO_NEW_DNA`: All inputs already exist in ledger.
- `ERROR`: Fatal failure (e.g., IO, Rule Load). Item-level errors are recorded but don't stop the batch.

## Invariants
- A DNA string in the ledger MUST have a corresponding entry in the JSON/CSV output (eventual consistency via atomic commit).
- The `toSequence.txt` is only cleared if the batch process completes without a `PersistenceError`.

## Error Classes
- `RuleLoadError`: Rules folder missing or JSON invalid.
- `RuleParseError`: DNA string doesn't match schema.
- `PersistenceError`: Atomic write/rename failure.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- The batch outputs (`parsed.json`, `parsed.csv`, `processed_ledger.json`) are updated in a single atomic transaction using temporary files and `os.replace`.

## Required Logs
- `[Idempotency] key=<DNA> dedupe_hit=<bool> terminal_outcome=<status>`
- `[OK] Processed <N> new DNA strings.`
- `[ERROR] <ErrorMessage>`
- Correlation ID (planned) to group logs per batch.
