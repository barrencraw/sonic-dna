# Contract: DNA Batch Processing Chain

## Overview
This contract defines the operational boundaries and invariants for the DNA batch parsing chain.

## 1. Trigger
- New non-empty lines appended to `data/raw/toSequence.txt`.

## 2. Inputs
- **DNA Strings**: One or more raw Sonic DNA sequences.
- **Correlation ID**: A UUIDv4 generated at the entry point (`main.py`) to trace the batch lifecycle.

## 3. Terminal States
- `SUCCESS`: DNA sequence successfully parsed and persisted to JSON, CSV, and Ledger.
- `DEDUPE_SKIP`: DNA sequence found in `ledger.json` and skipped to maintain idempotency.
- `PARSE_ERROR`: DNA sequence does not match any known rule; recorded in outputs as an error.
- `ATOMIC_FAILURE`: Critical I/O or persistence error; no files are updated, and the input file is not cleared.

## 4. Invariants
- **Idempotency**: The `ledger.json` file serves as the single source of truth for processed sequences.
- **Atomicity**: Updates to `toSequence_parsed.json`, `toSequence_parsed.csv`, and `ledger.json` must be atomic (all-or-nothing).
- **Naming Standards**: The canonical name for DNA data is `dna_sequence`. Legacy fields (e.g., `dna`) must be migrated.
- **Thermal Safety**: The system accumulation heat per item and refuses processing if `MAX_HEAT` (10.0) is exceeded.

## 5. Telemetry
All logs must use the `JSON_LOG:` prefix and include:
- `timestamp` (ISO 8601)
- `correlation_id`
- `chain_name`: `dna_batch_processing`
- `step`: (e.g., `start`, `parse`, `persist`, `end`)
- `outcome`: (e.g., `success`, `error`, `skipped`)
- `latency_ms`

## 6. Grep Recipe
```bash
grep "JSON_LOG:" | jq .
```
