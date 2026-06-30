# Chain Contract: DNA Batch Parsing

## Trigger
- Addition of new DNA strings to `data/raw/toSequence.txt`.
- Execution of `main.py` (Watcher or `--once` mode).

## Inputs
- `dna_sequence`: A string representing encoded audio properties.

## Terminal States
- `SUCCESS`: DNA parsed successfully and recorded in output files.
- `ERROR`: DNA malformed or rule not found.
- `SKIPPED`: DNA already exists in the ledger (Idempotency hit).
- `REFUSED`: System-level refusal (e.g., thermal lockout, though not implemented in this chain yet).

## Invariants
- **Consistency**: All output files (JSON, CSV) and the ledger must be updated in a single atomic transaction.
- **Idempotency**: Re-processing the same DNA string must not result in duplicate entries in output files.
- **Drainage**: The input file `toSequence.txt` must only be cleared if the batch processing completes successfully.

## Error Classes
- `DNAProcessingError`: Generic base error for the chain.
- `RuleLoadError`: Failure to load parsing rules from the `rules/` directory.
- `RuleParseError`: Failure to parse a specific DNA string against its rule.
- `PersistenceError`: Failure to write or commit output files atomically.

## Idempotency Key
- `dna_sequence`: The unique DNA string itself.

## Atomicity Boundary
- The "Atomic Write + Commit" block in `utils/dna_ui.py` covering:
    - `data/output/toSequence_parsed.json`
    - `data/output/toSequence_parsed.csv`
    - `data/processed_ledger.json`

## Required Logs
- Start log with `correlation_id`.
- Per-item log with `idempotency_key`, `dedupe_hit`, and `outcome`.
- End log with `new_processed_count` and summary.
- All logs prefixed with `JSON_LOG:`.

## Grep Recipes for Analysis
- **Extract all structured logs**: `grep 'JSON_LOG:'`
- **Format as pretty JSON**: `grep 'JSON_LOG:' | sed 's/JSON_LOG: //' | jq '.'`
- **Count outcomes by type**: `grep 'JSON_LOG:' | sed 's/JSON_LOG: //' | jq -r '.outcome' | sort | uniq -c`
- **Find errors with details**: `grep 'JSON_LOG:' | grep 'batch_error' | jq '.'`
- **Trace a specific batch**: `grep 'CORRELATION_ID' | grep 'JSON_LOG:'` (replace `CORRELATION_ID` with actual ID)
