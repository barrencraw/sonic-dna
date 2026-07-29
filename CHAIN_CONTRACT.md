# SonicDNA: DNA Batch Parsing Chain Contract

This document specifies the mini Chain Contract for the DNA Batch Parsing chain, ensuring robustness against torn writes, processing failures, and duplicate input processing.

## 1. Trigger
The batch parsing chain is triggered by:
- The background file watcher loop detecting new, non-empty DNA sequence string(s) appended/written to `data/raw/toSequence.txt`.
- Manual/direct CLI execution of `main.py --once`.

## 2. Inputs
- A text file `data/raw/toSequence.txt` containing one raw DNA sequence string per line (whitespace-stripped, non-empty).

## 3. Terminal States
- **Success:** All new valid DNA sequence strings are parsed, appended to the JSON and CSV output files atomically, the processed ledger is updated atomically, and the input file is cleared.
- **Skipped / Deduplicated:** DNA sequence strings that already have terminal outcomes (both `success` and `error` formats) in the processed ledger are skipped entirely. No new files are written, and the input file is cleared.
- **Failure / Error:** Critical processing/infrastructure errors (e.g. file system permissions, invalid configuration, rule loading failure, or atomic rename failure) raise standard typed `DNAProcessingError` subclasses, and the input file is **not** cleared, facilitating investigation and retries.

## 4. Invariants
- **Deduplication / Idempotency:** The system must never re-process a DNA string that has already completed processing with a terminal outcome (`success` or `error`).
- **Atomic Operations:** Both the parsed results (JSON and CSV) and the ledger file must never be written in a partially complete, corrupted, or torn state. They must always use the flush, fsync, and replace atomic write pattern.
- **Incremental Ledger Persistence:** Every newly processed sequence must have its result recorded with a precise timestamp.

## 5. Error Classes
- `DNAProcessingError`: The base class for all DNA batch parsing exceptions.
- `RuleLoadError`: Raised when the rule JSON schema files fail to load from the disk.
- `PersistenceError`: Raised when an atomic write, flush, fsync, or rename operation fails.

## 6. Idempotency Key
- The raw DNA sequence string itself (e.g. `"VOL08900750712"`).

## 7. Atomicity Boundary
- **Ledger file (`processed_ledger.json`):** Committed atomically via `save_ledger` using temporary file creation, flush, fsync, and `os.replace`.
- **Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`):** Refactored to write atomically to a temporary folder on the same directory/volume, flush, fsync, and replace, only when `new_processed_count > 0`.

## 8. Required Logs
To maintain complete observability and signal, the following structured logs are emitted:
- `[Idempotency] key=<dna> dedupe_hit=True terminal_outcome=<outcome>` (on skip)
- `[Idempotency] key=<dna> dedupe_hit=False terminal_outcome=processing` (on parse start)
- `[Idempotency] key=<dna> dedupe_hit=False terminal_outcome=<outcome>` (on parse finish)
- `[OK] Processed <count> new DNA strings. Total in ledger: <total>` (on completion)
