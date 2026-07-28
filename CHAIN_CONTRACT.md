# DNA Batch Parsing Chain Contract

## Triggers
- Background File Watcher (`main.py` watcher thread)
- Direct CLI invocation (`main.py --once` execution)

## Inputs
- File: `data/raw/toSequence.txt` containing one or more DNA string sequences.

## Terminal States
- `success`: DNA sequence parsed correctly, added to cumulative stores.
- `error`: DNA sequence failed to parse, or save operations failed, recorded with error detail.
- `skipped`: DNA sequence skipped due to deduplication (already present in the ledger).
- `refused`: System refused processing (e.g. thermal fatigue lockout / constraint violations).

## Invariants
- **Idempotency**: Previously processed DNA sequences with a terminal outcome (`success` or `error`) must not be processed again.
- **Atomicity**: Changes to output files and ledger are made atomically using temp files and atomic renames. Outputs are only updated/rewritten if at least one new sequence was processed (`new_processed_count > 0`).
- **No Silent Drains**: Any core processing or saving failures must be propagated as exceptions and caught appropriately by the caller (preventing clearing of the input queue on failure).

## Error Classes
- `DNAProcessingError`: Generic DNA processing exception.
- `RuleLoadError`: Rules folder or specific rules cannot be loaded.
- `PersistenceError`: Writing/moving results to output files failed.
- `LedgerSaveError`: Saving the ledger atomically failed (subclass of `PersistenceError`).

## Idempotency Key
- The raw DNA string sequence itself.

## Atomicity Boundary
- File writes (`toSequence_parsed.json`, `toSequence_parsed.csv`) are written to temp files first, flushed, fsynced, and then replaced.
- Truncation of `toSequence.txt` only occurs if the processor succeeds.

## Required Logs (Structured Telemetry)
Standardized JSON format logs with `JSON_LOG:` prefix containing the following fields:
- `timestamp`: precise ISO 8601 UTC timestamp format `%Y-%m-%dT%H:%M:%SZ`.
- `correlation_id`: unique UUID correlation string.
- `actor_id`: who initiated (e.g., `system`, `user`).
- `chain_name`: identifier for the chain (`DNA_Batch_Parsing`).
- `step`: specific step (e.g., `batch_start`, `process_dna`, `batch_end`).
- `outcome`: lowercase outcome value representing `DNAStatus`.
- `latency_ms`: duration of operation in milliseconds.
- `idempotency_key`: key used for deduplication.
- `outcome_detail`: human-readable description of outcome/details.
