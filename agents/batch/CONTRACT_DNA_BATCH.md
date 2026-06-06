# Contract: DNA Batch Parsing Chain

## Overview
The DNA Batch Parsing Chain is responsible for taking a collection of DNA strings from a raw input file, parsing them according to established rules, and persisting the results in structured JSON and CSV formats, while maintaining a ledger of processed items to ensure idempotency.

## Win Condition
Consolidate DNA batch processing into a single atomic transaction that includes the ledger update.

## Done When
- [ ] Logic bug in `utils/dna_ui.py` (ledger update outside loop) is fixed.
- [ ] `ledger.json` is included in the atomic `os.replace` commit block.
- [ ] Redundant non-atomic writes are removed.
- [ ] Structured JSON logging with `correlation_id` and `idempotency_key` is implemented.
- [ ] Regression tests for atomicity and structured logging pass.

## Trigger
- Background watcher detecting changes in `data/raw/toSequence.txt`.
- Manual execution via `main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: A text file where each non-empty line is a DNA string.
- `rules/`: A directory containing JSON rule definitions for various DNA variables.

## Terminal States
- **SUCCESS**: All new DNA strings in the input file were successfully parsed and persisted.
- **DEDUPE_SKIP**: A DNA string was found in the ledger and skipped to prevent duplicate processing.
- **PARSE_ERROR**: A DNA string failed to parse according to the rules; the error is recorded in the outputs.
- **ATOMIC_FAILURE**: A failure occurred during the persistence phase (e.g., disk full, permission denied); no changes were committed to the output files or the ledger.

## Invariants
- **Atomicity**: Either all changes (JSON, CSV, and Ledger updates) are committed together, or none are.
- **Idempotency**: Processing the same DNA string multiple times results in only one entry in the outputs and ledger.
- **Data Integrity**: Output files are never left in a partially written or corrupted state.

## Error Classes
- `RuleLoadError`: Failed to load rule definitions from the `rules/` directory.
- `RuleParseError`: Failed to parse an individual DNA string.
- `PersistenceError`: Failed to write or move output files atomically.
- `DNAProcessingError`: Generic base class for errors in the DNA processing chain.

## Idempotency Key
- Raw DNA string (`dna_sequence`) serves as the unique idempotency key in the ledger.

## Atomicity Boundary
- The boundary encompasses the writing of the `toSequence_parsed.json`, `toSequence_parsed.csv`, and `ledger.json` files. This is achieved using a temporary directory and atomic `os.replace` calls.

## Required Logs
- `JSON_LOG:` prefixed entries containing:
    - `timestamp` (ISO 8601)
    - `correlation_id` (UUID)
    - `chain_name`: "dna_batch_parsing"
    - `step`: (e.g., "start", "item_processing", "commit", "complete")
    - `outcome`: (e.g., "success", "skipped", "error")
    - `idempotency_key`: The DNA string being processed.

## Grep Recipe
```bash
# Extract and format all DNA batch parsing logs
grep "JSON_LOG:" | jq .
```
