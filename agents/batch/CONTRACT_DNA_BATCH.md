# Contract: DNA Batch Chain

## Trigger
- File creation or modification of `data/raw/toSequence.txt`.
- Manual invocation of `utils.dna_ui.main()`.

## Inputs
- `dna_sequences`: List of DNA strings to be processed.

## Terminal States
- `SUCCESS`: DNA string parsed and added to outputs.
- `PARSE_ERROR`: DNA string failed to parse due to rule violation.
- `SKIPPED`: DNA string already present in ledger (deduplicated).

## Invariants
- Atomicity: JSON, CSV, and Ledger updates are committed together or not at all.
- Idempotency: Duplicate DNA strings in the same or future batches are processed once.
- Canonical Naming: Use `dna_sequence` for the raw DNA string in all records.

## Required Logs
- Structured JSON logs via `log_structured`.
- Must include: `correlation_id`, `idempotency_key`, `step`, `outcome`.

## Telemetry Grep Recipes
- Track batch progress: `grep "dna_batch_chain" | grep "SUCCESS"`
- Identify failed parses: `grep "dna_batch_chain" | grep "PARSE_ERROR"`
- Check deduplication hits: `grep "dna_batch_chain" | grep "SKIPPED"`

## Error Classes
- `DNAProcessingError`: Generic base error.
- `RuleLoadError`: Failed to load JSON rules.
- `PersistenceError`: Atomic write or file system failure.
- `DataIntegrityError`: Existing output files are corrupted and cannot be loaded.
