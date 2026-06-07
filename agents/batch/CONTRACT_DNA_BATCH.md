# Contract: DNA Batch Parsing Chain

## Overview
This chain processes batch DNA sequences from a raw text file, parses them using defined rules, and persists the results in JSON and CSV formats while maintaining an idempotency ledger.

## Trigger
- CLI: `python main.py --once`
- Watcher: Background thread monitoring `data/raw/toSequence.txt`

## Inputs
- **DNA Source:** `data/raw/toSequence.txt` (one sequence per line)
- **Rules:** `rules/*.json`
- **Ledger:** `data/processed_ledger.json`

## Terminal States
- `SUCCESS`: Item parsed and scheduled for commit.
- `DEDUPE_SKIP`: Item already exists in ledger, skipped.
- `PARSE_ERROR`: Item failed validation/parsing; recorded as error in outputs.
- `ATOMIC_FAILURE`: Critical failure during commit phase; no files modified.

## Invariants
1. **Idempotency:** A `dna_sequence` successfully processed or marked as `PARSE_ERROR` must not be re-processed if present in the ledger.
2. **Atomicity:** JSON, CSV, and Ledger updates must be committed together. If any part of the write fails, none of the files should be updated.
3. **Naming:** The primary key for DNA strings is `dna_sequence`.

## Error Classes
- `RuleLoadError`: Failed to load or parse rule definitions.
- `PersistenceError`: Failed to write output files atomically.
- `DNAProcessingError`: Generic processing failure.
- `RuleParseError`: DNA sequence does not match rule schema.

## Telemetry
- Start/End logs for the batch.
- Per-item logs with `idempotency_key` and `outcome`.
- `correlation_id` propagated across all logs.
- Prefix: `JSON_LOG:`

## Done When
- [ ] Ledger is updated atomically with outputs.
- [ ] `dna_sequence` is used consistently.
- [ ] `JSON_LOG:` entries are present for start/step/end.
- [ ] `tests/test_idempotency.py` passes.
- [ ] `tests/test_atomicity_refined.py` passes.
