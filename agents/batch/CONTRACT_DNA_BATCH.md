# DNA Batch Parsing Contract

## Overview
Robust, atomic, and idempotent processing of DNA sequences from a raw text file into structured JSON/CSV formats with a persistence ledger.

## Contract
- **Trigger**: `utils.dna_ui.main(correlation_id)`
- **Inputs**:
    - Raw input file: `data/raw/toSequence.txt` (one DNA string per line)
    - Rules directory: `rules/`
    - Ledger: `data/processed_ledger.json`
- **Terminal States**:
    - `SUCCESS`: All new sequences processed, files committed, input file cleared.
    - `PARSE_ERROR`: A specific sequence failed rules; recorded in output as error, batch continues.
    - `ATOMIC_FAILURE`: Critical IO error during file swap; no state changes persisted.
- **Invariants**:
    - **Atomicity**: The JSON output, CSV output, and Ledger must be updated as a single atomic unit.
    - **Idempotency**: Processing the same DNA sequence twice (even across different batches) results in no duplicate entries in the outputs or ledger.
    - **Intra-batch Deduplication**: Multiple identical sequences in the same input file are processed only once.
    - **Input Integrity**: The source file is cleared ONLY if the persistence commit succeeds.
- **Error Classes**:
    - `RuleLoadError`: Rules folder missing or corrupted.
    - `PersistenceError`: Failed to write/rename output files or ledger.
    - `DNAProcessingError`: General batch failure.
- **Idempotency Key**: The DNA sequence string.
- **Atomicity Boundary**: The `os.replace` operations in the `commit` phase of `dna_ui.py`.
- **Required Logs**:
    - All logs must be prefixed with `JSON_LOG:`.
    - Fields: `timestamp`, `correlation_id`, `chain_name` ("dna_batch_chain"), `step`, `outcome`, `key` (idempotency key), `latency_ms`.

## Telemetry
- **Start**: `step="batch_started"`
- **Dedupe**: `step="dedupe_check"`, `outcome="hit"|"miss"`
- **Result**: `step="item_processed"`, `outcome="success"|"error"`
- **Commit**: `step="batch_committed"`, `outcome="success"`
- **Grep Recipe**: `grep "JSON_LOG:" | jq .`
