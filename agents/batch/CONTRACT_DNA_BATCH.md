# Contract: DNA Batch Parsing Chain

## Trigger
- **Watcher (`main.py`)**: Triggered by new content in `data/raw/toSequence.txt`.
- **CLI (`main.py --once`)**: Manual invocation to process existing content.

## Inputs
- `data/raw/toSequence.txt`: Text file with one DNA sequence per line.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Idempotency ledger.

## Terminal States
- `SUCCESS`: Item parsed and added to cumulative output.
- `DEDUPE_SKIP`: Item already in ledger or processed in current batch; skipped.
- `PARSE_ERROR`: Item failed validation/parsing; error recorded in output.
- `ATOMIC_FAILURE`: Persistence of output/ledger failed; whole batch rolled back.

## Invariants
1. **At-Least-Once Delivery → Exactly-Once Output**: Idempotency ledger ensures duplicate inputs don't create duplicate output records.
2. **Atomicity**: Either JSON, CSV, and Ledger are all updated, or none are.
3. **Data Integrity**: `dna_sequence` is the canonical key for all records.

## Idempotency Key
- The `dna_sequence` string itself.

## Atomicity Boundary
- All cumulative output files (`.json`, `.csv`) and the `processed_ledger.json` must be updated together via atomic renames.

## Required Logs (Structured JSON)
- `chain_name`: "dna_batch_parse"
- `step`: "start", "item_process", "commit", "end"
- `outcome`: "success", "error", "skipped"
- `correlation_id`: Unique UUID for the batch run.
- `idempotency_key`: The DNA sequence being processed.
- `latency_ms`: Time taken for the step.
