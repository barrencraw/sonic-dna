# Chain Contract: DNA Batch Parsing

## Description
The `dna_batch_chain` processes a list of DNA strings from a raw text file, calculates properties using the `DNACalculator`, and appends results to cumulative JSON and CSV stores. It maintains an idempotency ledger to avoid redundant processing.

## Trigger
- CLI: `python3 main.py --once`
- Watcher: `main.py` detects changes in `data/raw/toSequence.txt`.

## Inputs
- `data/raw/toSequence.txt`: Raw DNA strings.
- `data/processed_ledger.json`: Persistent idempotency ledger.
- `rules/*.json`: Domain rules for parsing.

## Terminal States
- `SUCCESS`: Batch processed and committed.
- `ERROR`: Fatal infrastructure or logic failure; no state changed.
- `NO_NEW_DNA`: No work to perform.

## Invariants
1. **Atomic Commit:** JSON output, CSV output, and Ledger are updated together. If one fails, none are updated.
2. **Idempotency:** The DNA string is the key. Double-invocation for the same string results in no-op.
3. **Queue Draining:** Input file is only cleared if the atomic commit succeeds.

## Error Classes
- `DNAProcessingError`: Generic failure in the chain.
- `RuleLoadError`: Configuration/rule loading failed.
- `PersistenceError`: Atomic write/rename failed.

## Idempotency Key
- The raw DNA string (e.g., `V100`).

## Required Logs
- `[START]`: Chain initialization.
- `[Idempotency]`: Trace for hits and misses.
- `[OK]`: Summary of processed items.
- `[OBSERVABILITY]`: Structured JSON with `correlation_id`, `actor_id`, `step`, `outcome`, `latency_ms`.

## Triage / Win Condition
- **Win Condition:** Unified atomic commit of all outputs.
- **Done When:**
    - `test_atomicity.py` passes (proving no torn state on disk full/crash).
    - `tests/test_idempotency.py` passes (proving no duplicate entries).
    - `[OBSERVABILITY]` logs contain `correlation_id` and `latency_ms`.
