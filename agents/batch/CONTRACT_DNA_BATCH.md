# DNA Batch Parsing Contract

## Trigger
- Addition of new DNA strings to `data/raw/toSequence.txt`.

## Inputs
- DNA strings (e.g., `VOL08900750712`).

## Terminal States
- SUCCESS: DNA parsed and added to JSON/CSV output.
- DEDUPE_SKIP: DNA already in ledger, skipped.
- PARSE_ERROR: DNA malformed, recorded as error in JSON/CSV.
- ATOMIC_FAILURE: Persistent failure to write output files.

## Invariants
- Idempotency: Same DNA string never results in duplicate entries in output files.
- Atomicity: JSON, CSV, and Ledger are always in sync; either all are updated or none are.

## Error Classes
- `RuleLoadError`: Failure to load parsing rules.
- `PersistenceError`: Failure to write output files atomically.
- `DNAProcessingError`: Generic processing failure.

## Idempotency Key
- The raw DNA string itself.

## Required Logs
- `key`: Idempotency key.
- `dedupe_hit`: Boolean indicating if item was skipped.
- `terminal_outcome`: Final status of the item.

## Grep Recipe
`grep -E "key=|dedupe_hit=|terminal_outcome="`
