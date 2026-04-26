# Chain Contract: DNA Batch Parsing

## Overview
This chain handles the batch processing of DNA strings from a raw text file, producing structured JSON and CSV outputs while maintaining an idempotency ledger.

## Trigger
- Background Watcher in `main.py` (polling `data/raw/toSequence.txt`).
- Direct invocation via `python main.py --once`.

## Inputs
- `toSequence.txt`: A newline-delimited file of DNA strings.
- `rules/*.json`: Rule definitions for various audio properties.

## Terminal States
- `SUCCESS`: All DNA strings processed and committed.
- `PARTIAL_SUCCESS`: Some strings succeeded, some failed, results committed.
- `ERROR`: Critical failure (e.g., IO, Rule Load) prevented processing/commitment.
- `NO_NEW_DNA`: No new strings to process (all skipped by idempotency).

## Invariants
- **Atomic Commit**: JSON, CSV, and Ledger are updated together or not at all.
- **Idempotency**: A DNA string already in the ledger with a terminal outcome is never re-processed.
- **Order Preservation**: DNA strings are processed in the order they appear in the input file.

## Error Classes
- `RuleLoadError`: Failed to load JSON rules from disk.
- `RuleParseError`: DNA string does not match any rule or is malformed.
- `PersistenceError`: Failed to write or move output files atomically.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- The writing of `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` is wrapped in an atomic replace operation using a temporary directory.

## Telemetry (Observability)
- **Format**: `| TELEMETRY | { ...json... }`
- **Fields**: `timestamp`, `correlation_id`, `step`, `outcome`, `dna`, `rule`, `latency_ms`, `error`.
- **Grep Recipe**:
    - `grep "TELEMETRY" logs.txt` -> All structured logs.
    - `grep "ERROR" logs.txt` -> High-level error reports.
    - `grep "VOL08900750712" logs.txt` -> Trace all actions for a specific DNA.
