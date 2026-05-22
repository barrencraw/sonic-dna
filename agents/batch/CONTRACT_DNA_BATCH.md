# DNA Batch Processing Contract

## Overview
The DNA Batch Processing chain is responsible for transforming raw DNA strings from `toSequence.txt` into structured JSON and CSV formats, while maintaining a processing ledger for idempotency and ensuring atomic commits to prevent data corruption.

## Contract DNA Batch
- **Trigger**: Application startup (watcher detects file content) or manual CLI execution (`--once`).
- **Inputs**:
    - `data/raw/toSequence.txt`: New DNA strings (one per line).
    - `rules/*.json`: Domain rules for parsing.
    - `data/processed_ledger.json`: State of previously processed strings.
- **Terminal States**:
    - `SUCCESS`: All new strings processed and outputs committed.
    - `PARTIAL_FAILURE`: Some strings failed parsing, but the results (including errors) were committed to output and ledger.
    - `CRITICAL_FAILURE`: System error (IO, Rule Loading) prevented any processing or commit.
- **Invariants**:
    - **Atomicity**: `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` must be updated together or not at all.
    - **Idempotency**: DNA strings already present in the ledger must not be re-processed or added as duplicates to output files.
- **Error Classes**:
    - `RuleParseError`: Individual DNA string failed domain validation (Handled: recorded as error).
    - `RuleLoadError`: Rules folder is missing or corrupt (Critical).
    - `PersistenceError`: Failed to write files to disk (Critical).
- **Required Logs**:
    - `dna_batch_start`: includes `correlation_id` and input count.
    - `dna_sequence_step`: includes `correlation_id`, `idempotency_key`, and `outcome`.
    - `dna_batch_end`: includes `correlation_id`, `success_count`, and `total_count`.

## Telemetry Grep Recipes
- **Identify failed parses in batch**:
  `grep "error:" data/output/toSequence_parsed.json`
- **Track progress for a specific batch**:
  `grep "<correlation_id>" logs/app.log` (if logs redirected) or piped output.
- **Check deduplication hits**:
  `grep "skipped" | grep "dedupe_hit"`
- **List all processed sequences in a batch**:
  `grep "sequence_step" | grep "success" | jq .idempotency_key` (if using jq on JSON logs).
