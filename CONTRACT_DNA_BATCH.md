# Chain Contract: DNA Batch Parsing

## Description
Processes a batch of DNA strings from a raw text file, parses them using rule-based logic, and persists the results in JSON and CSV formats while maintaining an idempotency ledger.

## Trigger
- File watcher detecting changes in `data/raw/toSequence.txt`.
- Manual execution via `main.py --once`.
- Background loop in GUI mode.

## Inputs
- `data/raw/toSequence.txt`: Newline-delimited DNA strings.
- `rules/*.json`: Rule definitions for different audio variables.
- `data/processed_ledger.json`: Record of previously processed DNA strings.

## Terminal States
- `SUCCESS`: All new DNA strings processed and persisted.
- `ERROR`: A critical failure occurred (e.g., rule loading, persistence).
- `SKIPPED`: DNA string already exists in the ledger.
- `NO_NEW_DNA`: Input file is empty or contains only already-processed strings.
- `PARTIAL_SUCCESS`: Some strings failed parsing but others succeeded and were persisted.

## Invariants
- **Idempotency**: A DNA string is never parsed more than once if it exists in the ledger with a terminal outcome.
- **Atomicity**: `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` are updated together. If any write fails, none should be permanently altered.

## Error Classes
- `RuleLoadError`: Rules folder missing or JSON files invalid.
- `RuleParseError`: DNA string does not conform to any rule.
- `PersistenceError`: Failed to write output files to disk.

## Idempotency Key
- The raw DNA string itself.

## Atomicity Boundary
- The `os.replace` calls following the successful write to the temporary directory.

## Required Logs (Structured)
- `timestamp`: ISO8601 UTC.
- `correlation_id`: UUID4 for the batch run.
- `chain_name`: `dna_batch_chain`.
- `step`: `parse`, `persist`, `complete`.
- `outcome`: From `Outcome` Enum.
- `idempotency_key`: The DNA string.
- `latency_ms`: Duration of the step.
- `actor_id`: Username of the executor.

## Grep Recipes for Telemetry Triage
- Failures: `grep "outcome=ERROR" observability.log`
- Specific DNA: `grep "idempotency_key=VOL0890" observability.log`
- Run Summary: `grep "step=complete" observability.log`
