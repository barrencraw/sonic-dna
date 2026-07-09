# DNA Batch Processing Chain Contract

## Trigger
- **Watcher**: Monitoring `data/raw/toSequence.txt` for new content.
- **Manual**: CLI invocation via `python3 main.py --once`.

## Inputs
- **Source**: `data/raw/toSequence.txt` (one DNA sequence per line).
- **Idempotency Key**: The DNA string itself.

## Terminal States
- **SUCCESS**: DNA parsed successfully and results recorded.
- **ERROR**: DNA parsing failed (e.g., `RuleParseError`); error recorded in ledger/outputs.
- **SKIPPED**: DNA already exists in the ledger with a terminal state; processing bypassed.

## Invariants
- **Atomic Multi-File Commit**: The Ledger, JSON output, and CSV output must be updated in a single transaction. Failure at any point must leave all three in their previous state.
- **No Silent Drains**: The input file (`toSequence.txt`) is only cleared if the batch processor completes without unhandled exceptions.
- **Idempotency**: Reprocessing the same DNA string results in a `SKIPPED` state and no duplicate entries in outputs.

## Error Classes
- **RuleParseError**: Specific to DNA grammar violations.
- **PersistenceError**: Infrastructure failure during the atomic commit phase.
- **DNAProcessingError**: General catch-all for batch processing failures.

## Required Logs (Telemetry)
- **Format**: `JSON_LOG: { "timestamp": "...", "correlation_id": "...", "step": "...", "outcome": "...", ... }`
- **Steps**: `batch_started`, `item_skipped`, `item_processed`, `commit_started`, `commit_completed`, `batch_completed`.
- **Grep Recipe**: `grep "JSON_LOG:" | sed 's/JSON_LOG: //g' | jq .`
