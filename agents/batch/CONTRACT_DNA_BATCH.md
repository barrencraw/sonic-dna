# Contract: DNA Batch Processing Chain

## Overview
The DNA Batch Processing Chain is responsible for reading raw DNA sequences from an input file, parsing them according to defined rules, and persisting the results in JSON and CSV formats. It ensures idempotency and atomic writes to maintain data integrity.

## Trigger
- Manual execution of `main.py --once`.
- Background watcher detecting changes in `data/raw/toSequence.txt`.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA sequence per line.
- `rules/*.json`: Rule definitions for parsing.

## Terminal States
- `success`: The DNA sequence was successfully parsed and recorded.
- `error`: The DNA sequence failed to parse or encountered a processing error.
- `skipped`: The DNA sequence was skipped because it was already processed (idempotency hit).
- `processing`: The initial state when an item enters the loop (used to detect hung processes if needed).

## Invariants
- **Idempotency**: Every unique `dna_sequence` is processed exactly once. Results are cached in the ledger.
- **Atomicity**: Output files (`.json`, `.csv`) and the ledger are updated atomically using a temporary-file-and-rename pattern.
- **Naming**: The field `dna_sequence` is the canonical key for DNA data.

## Error Classes
- `RuleLoadError`: Failed to load rule definitions.
- `RuleParseError`: Individual DNA sequence does not match any rule.
- `PersistenceError`: Failed to write output files to disk.

## Idempotency Key
- The `dna_sequence` string itself.

## Telemetry & Logging
- **Correlation ID**: A UUID v4 generated at the start of each batch.
- **Structured Logs**: Every step must log a JSON entry with:
  - `timestamp`
  - `correlation_id`
  - `chain_name`: "dna_batch_processor"
  - `step`: (e.g., "parse_item", "persist_batch")
  - `outcome`: One of the Terminal States.
  - `dna_sequence`: The sequence being processed.
  - `latency_ms`: Time taken for the step.
