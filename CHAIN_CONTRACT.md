# DNA Batch Processing Chain Contract

## 1. Overview
The DNA Batch Processing chain is responsible for reading raw DNA sequences from an input file, parsing them according to registered rules, and persisting the results into cumulative JSON and CSV formats while maintaining an idempotency ledger.

## 2. Trigger
- **Watcher (`main.py`)**: Triggered when `data/raw/toSequence.txt` contains new, non-empty content.
- **Manual (`main.py --once`)**: One-time execution reading all content in `toSequence.txt`.

## 3. Inputs
- `correlation_id`: A unique UUID string for end-to-end traceability of the batch.
- `actor_id`: The identifier of the system or user triggering the process (default: "system").
- `input_file`: Path to `data/raw/toSequence.txt`.

## 4. Terminal States (per DNA string)
- `SUCCESS`: Sequence parsed correctly and recorded.
- `ERROR`: Sequence failed parsing (e.g., invalid prefix, malformed data).
- `SKIPPED`: Sequence already exists in the ledger (idempotency hit).

## 5. Invariants
- **Atomic Multi-File Commit**: Ledger, JSON, and CSV outputs must be updated as a single logical transaction. No partial updates (e.g., JSON updated but Ledger not).
- **Idempotency**: A successfully processed DNA string must not be re-processed or duplicated in output files if re-encountered in the input.
- **Traceability**: Every batch run must have a unique `correlation_id` present in all logs and outputs.

## 6. Telemetry Schema
Logs are emitted with the prefix `JSON_LOG:` followed by a JSON object containing:
- `timestamp`: ISO 8601 UTC.
- `correlation_id`: Unique batch ID.
- `chain_name`: "dna_batch_processing".
- `step`: "start", "process_item", or "end".
- `outcome`: "success", "error", or "skipped".
- `dna_sequence`: The DNA string being processed (for `process_item`).
- `error_detail`: Description of any failure.

### Grep Recipe for Analysis:
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG://' | jq '.'
```

## 7. Error Classes
- `RuleLoadError`: Failed to load JSON rules from the `rules/` directory.
- `RuleParseError`: Individual DNA sequence does not match schema.
- `PersistenceError`: Failed to write output files to disk (e.g., disk full, permission denied).
