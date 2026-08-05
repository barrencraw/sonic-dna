# Chain Contract: DNA Batch Parsing

This document defines the formal contract for the **DNA Batch Parsing** processing chain in SonicDNA.

## 1. Triggers
- **Watcher Process:** Triggered automatically in the background when new non-empty content is appended to the input queue file.
- **CLI/Console Command:** Triggered manually when the system is run with the `--once` flag.

## 2. Inputs
- **Primary Queue File:** `data/raw/toSequence.txt` containing one or more DNA sequence strings (one per line).
- **Rule Configuration Files:** Located under the `rules/` directory, defining valid prefixes and subvariable schemas.
- **Idempotency Ledger:** `data/processed_ledger.json` containing the history of all previously processed sequences and their terminal states.

## 3. Terminal States & Outcomes
The chain resolves into one of the following terminal states:
- **`success`:** The DNA sequence was successfully parsed according to active rules. The results are stored in output datasets.
- **`error`:** The DNA sequence failed validation or parsing. The error detail is stored in output datasets.
- **`skipped`:** The sequence was previously parsed (found in the ledger with a terminal outcome of `success` or `error`) and is skipped to preserve idempotency.
- **`refused`:** Processing of the sequence was refused (e.g. system lockout/limitations).

## 4. Invariants
- **No Side-Effects on Deduplication:** If zero *new* DNA sequences are processed (all items in the batch are skipped), the output datasets (`toSequence_parsed.json`, `toSequence_parsed.csv`) and the ledger MUST NOT be modified or rewritten.
- **No Silent Failures:** Any critical exception during processing (such as disk full or syntax error) must interrupt processing and be propagated back to the orchestrator to prevent clearing the queue file.

## 5. Idempotency Key
- The **Idempotency Key** is the exact string content of each DNA sequence.
- All duplicate DNA sequences within a single batch, or across multiple invocations, are deduplicated and resolved without creating duplicate side-effects.

## 6. Atomicity Boundary
All updates to final destination files must succeed or fail together. If a crash or failure occurs during I/O:
1. No output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) or the ledger file (`processed_ledger.json`) shall be left in a partially-written or corrupted state (guaranteed by **Atomic Write + Commit** via temporary files and `os.replace`).
2. The input queue file `data/raw/toSequence.txt` MUST NOT be cleared on failure.

## 7. Error Classes
- **`DNAProcessingError`:** Base class for all domain-specific errors.
- **`InputReadError`:** Raised when reading the input queue file fails.
- **`RuleLoadError`:** Raised when the parsing rules folder cannot be loaded.
- **`PersistenceError`:** Base class for all storage operations.
- **`LedgerSaveError`:** Raised when writing the processed ledger fails.
- **`AtomicWriteError`:** Raised when writing output datasets fails.

## 8. Required Logs
All execution steps must emit standardized JSON logs with the prefix `JSON_LOG: ` and containing:
- `timestamp` (UTC ISO 8601 format)
- `correlation_id` (correlation token for distributed tracing)
- `actor_id` (defaults to "system")
- `chain_name` ("dna_batch_parsing")
- `step` (e.g. `"initialization"`, `"processing_start"`, `"deduplication"`, `"parse_item"`, `"processing_end"`, `"cleanup_failure"`)
- `outcome` (e.g. `"success"`, `"failed"`, `"skipped"`, `"error"`)
- `latency_ms` (latency of processing in milliseconds)
- `idempotency_key` (the DNA sequence identifier)
- `outcome_detail` (descriptive message)
