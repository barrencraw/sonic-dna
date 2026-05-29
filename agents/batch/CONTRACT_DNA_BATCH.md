# DNA Batch Parsing Contract

## Overview
This contract defines the execution and telemetry requirements for the DNA Batch Parsing chain.

## Trigger
- **Watcher (`main.py`)**: Detecting changes in `data/raw/toSequence.txt`.
- **CLI (`main.py --once`)**: Manual execution.

## Inputs
- File: `data/raw/toSequence.txt` (One DNA string per line).

## Terminal States (TerminalOutcome)
- `SUCCESS`: DNA string parsed successfully and added to output.
- `PARSE_ERROR`: DNA string failed validation/parsing.
- `SKIPPED`: DNA string was already in the ledger (idempotency hit).

## Invariants
- Every DNA string processed must result in a ledger entry.
- Output JSON and CSV must be updated atomically.
- Input file `toSequence.txt` is cleared only after successful processing and atomic write.

## Error Classes
- `RuleLoadError`: Failed to load rules from disk.
- `PersistenceError`: Failed to write output files atomically.
- `DNAProcessingError`: General processing failure.

## Idempotency
- **Key**: The DNA string itself.
- **Mechanism**: `data/processed_ledger.json` checks.

## Atomicity Boundary
- The batch run is atomic regarding output files (JSON, CSV).
- The input file clearing is the final "commit" in the watcher loop.

## Required Logs (Structured)
Format: `JSON_LOG: { ... }`
Fields:
- `timestamp`: ISO8601 or standard strftime.
- `correlation_id`: UUID linking all steps in a batch.
- `chain_name`: "dna_batch_parsing".
- `step`: "start", "process_sequence", "end".
- `dna`: (optional) The DNA string being processed.
- `outcome`: One of `TerminalOutcome` values.
- `error`: (optional) Error message if failed.

## Telemetry Grep Recipes
- `grep "JSON_LOG:"` : All structured logs.
- `grep "terminal_outcome=PARSE_ERROR"` : Find failed parses.
- `grep "dedupe_hit=True"` : Check for skipped duplicates.
