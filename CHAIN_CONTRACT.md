# Chain Contract: DNA Batch Parsing

## Trigger
- Launching `main.py` directly starts a background watcher thread monitoring `data/raw/toSequence.txt`.
- Running `main.py --once` executes the batch parser exactly once.

## Inputs
- A list of DNA sequence strings (non-empty, stripped lines) from `data/raw/toSequence.txt`.

## Terminal States
- **success**: DNA sequence successfully parsed and appended to cumulative JSON and CSV outputs.
- **error**: DNA sequence failed to parse against rules; error record appended to JSON and CSV outputs.
- **skipped**: Sequence was skipped (already exists in the processed ledger).
- **refused**: Execution is refused due to system limits or lockouts.

## Invariants
- **Idempotency**: DNA sequences that exist in the ledger with a terminal outcome (`success`, `error`) are skipped to prevent redundant processing.
- **Zero-Write Invariant**: If no new sequences are processed (`new_processed_count == 0`), output JSON and CSV files must not be written or touched.

## Error Classes
- `DNAProcessingError`: Base class.
- `RuleLoadError`: Raised when rules cannot be loaded.
- `PersistenceError`: Raised when output writes or renames fail.

## Idempotency Key
- The raw DNA sequence string itself.

## Atomicity Boundary
- **Atomic Outputs**: Writing to a temporary file inside a temporary directory, flushing and fsync'ing, and using `os.replace` to atomically replace the target outputs (`toSequence_parsed.json` and `toSequence_parsed.csv`).
- **Post-Commit Queue Drain**: Truncation/clearing of `data/raw/toSequence.txt` only happens after the batch parser executes successfully.

## Required Logs
- Structured logs with the following fields:
  - `idempotency_key`, `dedupe_hit`, `terminal_outcome`.
