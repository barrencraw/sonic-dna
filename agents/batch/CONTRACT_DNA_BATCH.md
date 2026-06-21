# DNA Batch Chain Contract

## Trigger
- Watcher detects new non-empty content in `data/raw/toSequence.txt`.
- Manual execution via `python main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.

## Terminal States
- `success`: DNA string parsed and added to JSON/CSV outputs.
- `error: <message>`: DNA string failed parsing; error recorded in JSON/CSV outputs.
- `skipped`: DNA string already present in ledger; no action taken.

## Invariants
- **Idempotency**: Processing the same DNA string multiple times results in only one entry in the output files.
- **Atomicity**: Either all output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and the ledger (`processed_ledger.json`) are updated successfully, or none are.

## Error Classes
- `RuleParseError`: Individual DNA string format is invalid.
- `RuleLoadError`: System failed to load the JSON rulesets.
- `PersistenceError`: System failed to write output files atomically (e.g., disk full, permissions).

## Idempotency Key
- The raw DNA string itself.

## Atomicity Boundary
- The `TemporaryDirectory` write-and-rename block in `utils/dna_ui.py`.

## Required Logs
- `batch_start`
- `item_process` (with `idempotency_key`, `outcome`, `latency_ms`)
- `persistence` (with `latency_ms`)
- `batch_complete` (with `latency_ms`, `new_items`, `total_in_ledger`)
