# DNA Batch Parsing Contract

## Trigger
- Content detected in `data/raw/toSequence.txt`.
- Manual invocation via `python3 main.py --once`.

## Inputs
- DNA Strings (one per line).
- `data/processed_ledger.json` (Idempotency Ledger).
- `data/output/toSequence_parsed.json` (Cumulative JSON).
- `data/output/toSequence_parsed.csv` (Cumulative CSV).

## Terminal States
- **SUCCESS**: DNA parsed successfully and added to outputs/ledger.
- **DEDUPE_SKIP**: DNA already exists in ledger, no action taken.
- **PARSE_ERROR**: DNA could not be parsed; error recorded in outputs/ledger.
- **ATOMIC_FAILURE**: Persistence failed; no changes to outputs or ledger.

## Invariants
- **Atomicity**: Ledger and output files are updated in a single atomic commit.
- **Idempotency**: Processing the same DNA string multiple times results in exactly one entry in the output.
- **Naming**: DNA field is canonically named `dna_sequence`.

## Error Classes
- `RuleLoadError`: Rules folder missing or corrupted.
- `DNAProcessingError`: Generic processing failure.
- `PersistenceError`: Atomic write/rename failure.

## Required Logs
All logs use the `JSON_LOG:` prefix and include:
- `timestamp` (ISO 8601)
- `correlation_id` (UUID)
- `chain_name`: `dna_batch_parsing`
- `step`: (`dedupe`, `parse`, `batch_commit`)
- `outcome`: (`success`, `error`, `dedupe_hit`, `dedupe_miss`)
- `idempotency_key`: The `dna_sequence` being processed.
