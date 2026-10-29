# SonicDNA Chain Contract: DNA Batch Parsing

## Overview
This document specifies the formal Mini Chain Contract for the **DNA Batch Parsing** chain in SonicDNA.

---

## Contract Specification

### 1. Chain Trigger
- **Watcher Trigger**: Periodic file polling loop in `main.py` monitoring `data/raw/toSequence.txt`.
- **Direct Trigger**: One-time execution via `python main.py --once` or programmatic call to `run_batch(correlation_id=None)`.

### 2. Inputs
- `data/raw/toSequence.txt`: Raw text file containing one DNA sequence per non-empty line.
- `rules/`: Directory containing JSON rule specifications (e.g., `rules_Volume.json`).
- `data/processed_ledger.json`: State file tracking previously processed DNA sequences and outcomes.

### 3. Terminal States
The outcome for every processed DNA sequence falls strictly into one of four `DNAStatus` string enum states:
- `success`: Sequence valid, parsed, and persisted in JSON/CSV outputs and ledger.
- `error`: Sequence invalid or rule parse error, recorded with error detail in JSON/CSV outputs and ledger.
- `skipped`: Sequence already recorded with terminal outcome in ledger (idempotency deduplication hit).
- `refused`: Sequence refused due to system constraint or overload condition.

### 4. Invariants
- **Atomicity**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and the processed ledger (`processed_ledger.json`) are updated atomically using staging files and `os.replace`. Partial/torn writes never occur on disk.
- **Deduplication**: Double-invocations with identical DNA sequences do not produce duplicate rows in output files.
- **Data Integrity**: Input file `data/raw/toSequence.txt` is cleared if and only if batch processing and persistence complete successfully.
- **Backward Compatibility**: JSON and CSV output entries retain canonical (`dna_sequence`) and legacy (`dna`) keys.

### 5. Error Taxonomy
All errors inherit from `DNAProcessingError`:
- `DNAProcessingError` (base class)
  - `RuleLoadError`: Rules folder missing or corrupt rule files.
  - `InputReadError`: Failure reading input file (`toSequence.txt`).
  - `PersistenceError`
    - `LedgerLoadError`: Corrupted or unreadable ledger file.
    - `LedgerSaveError`: Failed to persist ledger.
    - `AtomicWriteError`: Staging or atomic rename failed during I/O.

### 6. Idempotency Key Strategy
- **Key**: The raw trimmed DNA sequence string (e.g., `VOL08900750712`).
- **Store**: `data/processed_ledger.json` mapping `key` -> `{ "terminal_outcome": status, "timestamp": utc_iso }`.

### 7. Atomicity Boundary
1. Staging writes occur in a temporary directory inside `data/output/`.
2. Temp files are flushed (`jf.flush()`) and synced (`os.fsync()`) to disk before replacement.
3. Atomic renames (`os.replace`) commit `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json`.

### 8. Required Telemetry & Structured Logging
All telemetry logs are emitted to stdout prefixed with `JSON_LOG:` containing:
- `timestamp`: UTC ISO 8601 string.
- `correlation_id`: Trace UUID for the invocation.
- `actor_id`: Initiator identification (e.g., `batch_parser`, `watcher`).
- `chain_name`: `dna_batch_parsing`.
- `step`: Current pipeline step (e.g., `start`, `read_input`, `dedupe`, `parse_sequence`, `atomic_write`, `end`).
- `outcome`: State or progress (`success`, `error`, `skipped`, `refused`).
- `latency_ms`: Duration in milliseconds.
- `idempotency_key`: DNA sequence string (or null for batch-level logs).
- `outcome_detail`: Short descriptive message or error details.

---

## Telemetry Grep Recipes

```bash
# View all structured JSON logs:
grep "JSON_LOG:" execution.log

# Filter logs by correlation ID:
grep "JSON_LOG:" execution.log | grep "<correlation_id>"

# Filter deduplication (skipped) events:
grep "JSON_LOG:" execution.log | grep '"outcome":"skipped"'

# Check atomic write steps:
grep "JSON_LOG:" execution.log | grep '"step":"atomic_write"'
```
