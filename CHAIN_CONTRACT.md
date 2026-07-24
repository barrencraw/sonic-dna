# Chain Contract: DNA Batch Parsing

## 1. Trigger
- File watcher detecting changes to `data/raw/toSequence.txt`.
- Manual/CLI invocation with `--once` flag.

## 2. Inputs
- `dna_sequence_list`: A collection of parsed, non-empty DNA string sequences retrieved from `toSequence.txt`.
- `correlation_id` (optional): Unique uuid trace identifier passed from the initiator.

## 3. Terminal States (DNAStatus Enum)
- `success`: DNA sequence parsed successfully; outputs written to destination.
- `error`: DNA sequence failed to parse; error stored in the outputs.
- `skipped`: DNA sequence processing skipped (e.g. idempotency match).
- `refused`: Sequence processing refused due to systemic lockout (e.g. thermal lockout).

## 4. Invariants
- **Idempotency**: DNA sequences that are already recorded in the ledger with terminal state `success` or `error` must be skipped.
- **Output Sync**: The ledger, JSON outputs, and CSV outputs must never contain inconsistent/duplicate records.
- **No Silents**: All failures must trigger logs, preserve original exceptions, and propagate correctly.

## 5. Error Classes
- `DNAProcessingError`: Generic DNA processing failures.
- `RuleLoadError`: Rules folder loading issues.
- `PersistenceError`: IO/filesystem issues during result write.

## 6. Idempotency Key
- The `dna_sequence` string value itself.

## 7. Atomicity Boundary
- All outputs (JSON, CSV, and the processed ledger) are written atomically using temp-write, flush, fsync, and replace sequence, ensuring no torn writes occur.

## 8. Required Logs
- Structured JSON logs prefixed with `JSON_LOG:` with standard keys: `timestamp`, `correlation_id`, `actor_id`, `chain_name`, `step`, `outcome`, `latency_ms`, `idempotency_key`, `outcome_detail`.
