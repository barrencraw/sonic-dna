# Chain Contract: DNA Batch Parsing

## Overview
This chain handles the batch processing of DNA strings from a raw input file into structured JSON and CSV formats, maintaining an idempotency ledger to prevent redundant processing.

## Trigger
- **Watcher (`main.py`)**: Detects new content in `data/raw/toSequence.txt`.
- **Manual CLI**: Running `python3 utils/dna_ui.py` or `python3 main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.
- `rules/*.json`: Variable-specific parsing rules.
- `data/processed_ledger.json`: State tracking for idempotent execution.

## Terminal States
- **SUCCESS**: New DNA strings parsed and committed to outputs.
- **NO_NEW_DNA**: Input empty or all DNA already processed.
- **ERROR**: Rule loading, parsing, or persistence failure.
- **SKIPPED**: Individual DNA string already in ledger (dedupe hit).

## Invariants
- **Atomicity**: Either JSON, CSV, and Ledger are all updated successfully, or none are.
- **Idempotency**: Processing the same DNA string multiple times results in exactly one entry in the cumulative outputs.
- **Deduplication**: In-memory duplication handles duplicates within the same input file.
- **Input Integrity**: `toSequence.txt` is cleared only after a successful batch completion (handled by `main.py`).

## Error Classes
- `RuleLoadError`: Failed to load rule JSON files.
- `RuleParseError`: DNA string doesn't match rule prefix or has invalid structure.
- `PersistenceError`: Failed to write/rename output files atomically.

## Telemetry Triage (Grep Recipes)

### Check for any failures:
```bash
grep "\"outcome\": \"ERROR\"" logs.txt
```

### Identify specific DNA processing outcome:
```bash
grep "VOL08900750712" logs.txt
```

### Verify idempotency hits:
```bash
grep "\"outcome\": \"SKIPPED\"" logs.txt
```

### Get run summary:
```bash
grep -E "\"outcome\": \"START\"|\"outcome\": \"END\"" logs.txt
```

## Observability Schema
Logs are emitted as structured JSON strings:
```json
{
  "timestamp": "ISO8601 UTC",
  "correlation_id": "UUID",
  "chain_name": "dna_batch_chain",
  "step": "init|process_dna|atomic_commit|complete",
  "outcome": "START|END|SUCCESS|ERROR|SKIPPED|PROCESSING|NO_NEW_DNA",
  "latency_ms": 123,
  "actor_id": "username",
  "idempotency_key": "DNA_STRING",
  "error_message": "optional"
}
```
