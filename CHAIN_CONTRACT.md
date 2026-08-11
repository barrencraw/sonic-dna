# DNA Batch Parsing Chain Contract

## Trigger
- New raw DNA sequences appended to `data/raw/toSequence.txt`.
- Manual invocation of `utils/dna_ui.py`'s `run_batch()` or running `main.py --once`.

## Inputs
- `toSequence.txt`: A text file under `data/raw` where each line represents a single DNA sequence to be processed.

## Terminal States
- **SUCCESS**: All new DNA sequences are parsed successfully or skipped. Output JSON, output CSV, and the processed ledger are updated atomically on disk.
- **NO_NEW_ITEMS**: All input DNA sequences are already recorded in the ledger (deduplicated). No output or ledger files are modified.
- **FAILURE**: A typed processing error is raised (no output or ledger files are written or partially written, ensuring complete atomicity).

## Invariants
- **No silent/partial updates**: Either both output files and the ledger are successfully committed, or none are.
- **Deduplication**: Processing a DNA sequence already marked as terminal (`success` or `error`) in the ledger is skipped entirely, avoiding redundant I/O and parsing.
- **Corrupted Ledger Protection**: If `processed_ledger.json` is corrupted, the system halts with a load error rather than silently resetting or corrupting further.

## Error Classes
- `DNAProcessingError`: Base class for DNA processing exceptions.
- `InputReadError`: Subclass of `DNAProcessingError`, raised when reading the input file fails.
- `RuleLoadError`: Subclass of `DNAProcessingError`, raised when rule files cannot be loaded.
- `PersistenceError`: Subclass of `DNAProcessingError`, base class for filesystem storage failures.
- `LedgerLoadError`: Subclass of `PersistenceError`, raised when the ledger is corrupted on read.
- `LedgerSaveError`: Subclass of `PersistenceError`, raised when the ledger fails to save atomically.
- `AtomicWriteError`: Subclass of `PersistenceError`, raised when the output JSON/CSV cannot be written atomically.

## Idempotency Key
- The raw, stripped, non-empty DNA sequence string (e.g., `VOL08900750712`).

## Atomicity Boundary
1. Write the output JSON and CSV files atomically using a unique temporary directory on the same filesystem. Flush and `fsync` the file descriptors, then atomically rename (`os.replace`) them to their target destinations.
2. If output files write successfully, write the updated ledger atomically to a temporary file, flush and `fsync` it, and atomically rename it (`os.replace`) to its target destination.
3. If any step fails, clean up the temporary directory, raise a typed `PersistenceError` subclass, and retain the original input file so that the operation can be retried without losing data.

## Required Logs
- Start Log: Prints when starting processing of DNA sequences.
- Idempotency Logs:
  - Cache Hit: `[Idempotency] key={key} dedupe_hit=True terminal_outcome={outcome}`
  - Processing Start: `[Idempotency] key={key} dedupe_hit=False terminal_outcome=processing`
  - Processing Complete: `[Idempotency] key={key} dedupe_hit=False terminal_outcome={outcome}`
- Complete Log: `[OK] Processed {count} new DNA strings. Total in ledger: {total_count}`
