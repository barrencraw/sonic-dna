# Contract: DNA Batch Parsing

## Win Condition
Successfully parse a batch of DNA strings into structured JSON and CSV formats, ensuring each unique string is processed exactly once, and all system outputs are committed atomically.

## Terminal States
- **SUCCESS**: Batch completed. All new DNA strings parsed and persisted.
- **ERROR**: Batch failed due to I/O error, rule loading failure, or malformed persistence attempt.
- **DEDUPE**: (Step-level) DNA string skipped because it exists in the processed ledger.

## Invariants
1. **Idempotency**: A DNA string present in `data/processed_ledger.json` must not be re-processed.
2. **Atomicity**: `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` must be updated together. If any write fails, none of the files should be modified.
3. **Queue Drainage**: `data/raw/toSequence.txt` should only be cleared if the processing and persistence steps succeed.

## Observability Contract
All key lifecycle events are logged with the `[OBSERVABILITY]` prefix in JSON format.
- **Required Fields**: `correlation_id`, `chain_name` ("dna_batch_parser"), `step`.
- **Steps**:
    - `start`: Batch processing initiated.
    - `process_string`: Single DNA string outcome (`idempotency_key`, `outcome`).
    - `terminal`: Batch completion (`outcome`, `new_processed`, `latency_ms`).

## Telemetry Triage (Grep Recipes)
- View all observability logs:
  `grep "\[OBSERVABILITY\]" logs.txt`
- Filter by specific correlation ID:
  `grep "YOUR_UUID" logs.txt`
- Check for batch errors:
  `grep "\[OBSERVABILITY\].*\"outcome\": \"ERROR\"" logs.txt`
- Calculate average latency:
  `grep "\[OBSERVABILITY\].*\"step\": \"terminal\"" logs.txt | jq '.latency_ms'`
