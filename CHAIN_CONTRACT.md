# DNA Batch Processing Chain Contract

## Trigger
- Watcher (`main.py`) detects non-empty content in `data/raw/toSequence.txt`.
- Manual CLI invocation (`python main.py --once`).

## Inputs
- `data/raw/toSequence.txt`: File containing DNA strings, one per line.
- `rules/*.json`: Rule definition files for parsing.
- `data/processed_ledger.json`: Idempotency ledger.

## Terminal States
- `success`: Batch processed and committed atomically.
- `skipped`: No new DNA strings found or all strings were already in the ledger.
- `error`: Transient or persistent failure during processing (ledger and outputs not updated).

## Invariants
- Atomic write: `json`, `csv`, and `ledger` are updated together or not at all.
- Idempotency: Same DNA string is never added twice to cumulative outputs.

## Error Classes
- `RuleLoadError`: Critical failure to load rules.
- `DNAProcessingError`: Generic processing failure.
- `PersistenceError`: Critical failure writing outputs.

## Idempotency Key
- The DNA string itself.

## Required Logs (Structured)
- `batch_start`: Signal start of batch.
- `item_process`: Signal per-item outcome (success/error/skipped) and latency.
- `batch_end`: Signal batch completion and summary.

## Telemetry Grep Recipe
To analyze batch outcomes and correlation IDs:
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //' | jq '.'
```
To find slow items:
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //' | jq 'select(.step == "item_process" and .latency_ms > 100)'
```
