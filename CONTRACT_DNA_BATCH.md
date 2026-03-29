# DNA Batch Parsing Chain Contract

## Trigger
- **Watcher (`main.py`)**: Triggered when `data/raw/toSequence.txt` content changes.
- **Once-Runner (`main.py --once`)**: Triggered manually from the command line.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA string per line.
- `rules/*.json`: Rule definitions for different audio variables.

## Terminal States
- **SUCCESS**: DNA string parsed correctly and results stored.
- **ERROR**: DNA string failed validation or parsing; error recorded in ledger and outputs.
- **SKIPPED**: DNA string already exists in the ledger and was not re-processed.

## Invariants
- The **Ledger** (`data/processed_ledger.json`) must always be in sync with the cumulative outputs (**JSON** and **CSV**).
- No duplicate DNA strings should be processed (Idempotency).
- Partial writes to disk are forbidden; all outputs must be updated atomically.

## Error Classes
- `RuleParseError`: Raised when a DNA string does not conform to any rule or its specific schema.
- `PersistenceError`: Raised when the atomic write/commit to disk fails.
- `RuleLoadError`: Raised when rule JSON files cannot be loaded.

## Idempotency Key
- The **DNA string** itself (e.g., `VOL08900750712`).

## Atomicity Boundary
- The boundary includes:
    1. Updating the `processed_ledger.json`.
    2. Appending to `toSequence_parsed.json`.
    3. Appending to `toSequence_parsed.csv`.
- **Commit Pattern**: All three files are written to a temporary directory, flushed, synced, and then atomically renamed to their final locations.

## Required Logs
- `[START] Batch processing started.`
- `[Idempotency] key=... dedupe_hit=True/False terminal_outcome=...`
- `[OK] Processed X new DNA strings. Total in ledger: Y`
- `[END] Batch processing complete.`

## Triage / Grep Recipes
- Check for failures: `grep "[ERROR]" logs` or `grep "terminal_outcome=error" logs`
- Check for idempotency hits: `grep "dedupe_hit=True" logs`
- Verify atomicity completion: `grep "[OK]" logs`
