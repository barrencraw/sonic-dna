# Chain Contract: DNA Batch Processing

## Overview
This contract defines the behavior, invariants, and terminal states for the DNA Batch Processing chain (`dna_batch`).

## Trigger
- User appends DNA strings to `data/raw/toSequence.txt`.
- GUI or CLI invokes `utils.dna_ui.main()`.

## Inputs
- `toSequence.txt`: One DNA string per line.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Persistent state including idempotency and system heat.

## Invariants
- **Thermal Debt**: Each processed item adds +5.0 heat. Heat dissipates at 0.5 units/sec. Lockout occurs at >100.0 heat.
- **Atomicity**: Ledger and output files (JSON, CSV) must be updated together or not at all.

## Terminal States (DNAStatus)
- `SUCCESS`: Item parsed and recorded.
- `ERROR`: Item failed parsing (recorded as error entry).
- `SKIPPED`: Item already in ledger as `SUCCESS` (idempotency hit).
- `REFUSED`: Item processing refused due to thermal lockout.

## Error Classes
- `RuleLoadError`: Rules folder missing or malformed.
- `DNAProcessingError`: Generic I/O or unexpected failure.
- `PersistenceError`: Atomic write failure (ledger/outputs).
- `ThermalOverloadError`: (Internal) system exceeded heat capacity.

## Idempotency Key
- The raw `dna_sequence` string.

## Atomicity Boundary
- The writing of `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json`.

## Required Logs
- `JSON_LOG:` prefix for all structured telemetry.
- Fields: `timestamp`, `correlation_id`, `chain_name`, `step`, `outcome`, `actor_id`.
- Optional: `idempotency_key`, `latency_ms`, `error_detail`, `hint`.

## Telemetry Analysis (Grep Recipe)
```bash
# View all batch processing outcomes for a specific correlation ID
grep "JSON_LOG:" | grep "<correlation_id>"

# Count terminal outcomes in a session
grep "JSON_LOG:" | grep "item_process" | jq -r '.outcome' | sort | uniq -c

# Identify thermal lockout events
grep "JSON_LOG:" | grep "REFUSED"
```
