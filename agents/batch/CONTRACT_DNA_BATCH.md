# Chain Contract: DNA Batch Parser

## Overview
Hardens the core DNA processing loop against torn writes, duplicate processing, and observability gaps.

## Contract
- **Trigger:** Appearance of new content in `data/raw/toSequence.txt` or `--once` CLI flag.
- **Inputs:** `data/raw/toSequence.txt` (raw DNA strings).
- **Terminal States:**
    - `SUCCESS`: All new strings processed, outputs updated, input cleared.
    - `SKIPPED`: All strings in batch already exist in ledger.
    - `PARTIAL_FAILURE`: Some strings failed parsing (logged), others succeeded.
    - `FATAL`: Systemic failure (I/O, rules missing); input file preserved.
- **Invariants:**
    - No DNA string is processed twice if present in `processed_ledger.json`.
    - JSON output, CSV output, and Ledger are updated atomically (via temp dir + rename).
    - Input file is cleared only if the batch processing and atomic commit succeed.
- **Error Classes:**
    - `RuleLoadError`: Missing or corrupt JSON rules.
    - `DNAProcessingError`: Generic processing failure.
    - `PersistenceError`: Failure during atomic commit (write/rename).
- **Idempotency Key:** Canonical `DNASequence` string.
- **Atomicity Boundary:** The `os.replace()` calls for JSON, CSV, and Ledger files.
- **Required Logs:**
    - `correlation_id` (UUID per batch).
    - `chain_name`: `dna_batch_chain`.
    - `step`: `start`, `dedupe`, `parse`, `commit`, `end`.
    - `outcome`: `success`, `error`, `skipped`.
    - `idempotency_key`: The DNA string being processed.

## Done When
- [x] `utils/dna_ui.py` syntax errors are resolved.
- [x] Ledger update is part of the atomic commit transaction.
- [x] `test_atomicity.py` passes.
- [x] `tests/test_idempotency.py` passes.
- [x] Logs contain `correlation_id` and structured fields.
