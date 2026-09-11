# Chain Contract: DNA Batch Parsing

## Overview
The DNA Batch Parsing chain is responsible for reading raw DNA sequence strings from `data/raw/toSequence.txt`, parsing them according to rule definitions in `rules/`, and maintaining persistent outputs in `data/output/` alongside an idempotency ledger in `data/processed_ledger.json`.

---

## Contract Specification

### 1. Trigger
- **Automatic**: Background watcher loop in `main.py` detecting new non-empty content in `data/raw/toSequence.txt`.
- **Manual/Direct**: CLI batch command `python main.py --once` or direct python call to `utils.dna_ui.run_batch()`.

### 2. Inputs
- `toSequence.txt`: Raw text file containing one DNA sequence per line.
- `correlation_id`: String (UUID v4) trace context passed across batch calls.
- `actor_id`: String identifier for the calling component (defaults to `'batch_parser'`).

### 3. Terminal States
- `success`: DNA sequence parsed successfully against rules and recorded in output and ledger.
- `error`: Invalid DNA sequence or rule parsing failure; recorded as an error outcome in output and ledger.
- `skipped`: DNA sequence already recorded in processed ledger with a terminal outcome (`success` or `error`). Redundant processing is bypassed.
- `refused`: Processing halted due to systemic refusal or lockout conditions.

### 4. Invariants
- **Idempotency**: All processed DNA sequences are recorded in `data/processed_ledger.json`. Any re-submitted DNA sequence present in the ledger is skipped without re-parsing or adding duplicate entries to output files.
- **Atomicity**: Writes to output JSON (`data/output/toSequence_parsed.json`), output CSV (`data/output/toSequence_parsed.csv`), and ledger (`data/processed_ledger.json`) are committed atomically via temporary directory staging, `flush()`, `os.fsync()`, and `os.replace()`. Half-written or corrupted states on failure are impossible.
- **No Silent Drains**: Input file (`data/raw/toSequence.txt`) is truncated/cleared **only** after successful batch processing without unhandled exceptions.

### 5. Error Taxonomy
- `DNAProcessingError` (Base exception class)
  - `InputReadError`: Failure to access or read input file `toSequence.txt`.
  - `RuleLoadError`: Failure to initialize rules or `DNACalculator`.
  - `PersistenceError`: General I/O or persistence failure.
    - `LedgerLoadError`: Corrupted or unparseable `processed_ledger.json`.
    - `LedgerSaveError`: Failure to write or save ledger file.
    - `AtomicWriteError`: Failure during temp file creation, flush, fsync, or replacement of output files.

### 6. Idempotency Key Strategy
- **Key**: The raw DNA sequence string (`dna_sequence`).
- **Ledger Record**:
  ```json
  {
    "terminal_outcome": "success|error",
    "timestamp": "2026-03-02T10:00:00Z"
  }
  ```

### 7. Atomicity Boundary
1. Read input sequence list from `data/raw/toSequence.txt`.
2. Filter sequences against `processed_ledger.json`.
3. Parse non-deduplicated sequences.
4. Prepare temporary staging directory under `data/output/`.
5. Write JSON and CSV to temp directory, call `flush()` and `os.fsync()`.
6. Replace output JSON and CSV files atomically using `os.replace()`.
7. Write and sync updated ledger file.
8. Truncate `data/raw/toSequence.txt` (handled by caller on success).

### 8. Required Logs & Telemetry
Every step emits structured JSON logs prefixed with `JSON_LOG:` to standard output:
- `timestamp`: UTC ISO 8601 timestamp (`YYYY-MM-DDTHH:MM:SSZ`).
- `correlation_id`: UUID trace correlation identifier.
- `actor_id`: Component executing the action (e.g. `'batch_parser'`).
- `chain_name`: `'dna_batch_parser'`.
- `step`: Process step (`'start'`, `'dedupe_check'`, `'parse'`, `'commit'`, `'end'`).
- `outcome`: Terminal state or step outcome (`'success'`, `'error'`, `'skipped'`, `'refused'`, `'processing'`).
- `latency_ms`: Execution time in milliseconds for the step.
- `idempotency_key`: DNA sequence string associated with the log event.
- `outcome_detail`: Additional context or error message details.

---

## Grep Recipes

Filter all structured logs:
```bash
grep "JSON_LOG:" stdout.log
```

Filter logs for a specific correlation ID:
```bash
grep "JSON_LOG:" stdout.log | grep "<correlation_id>"
```

Filter deduplication hits (`skipped`):
```bash
grep "JSON_LOG:" stdout.log | grep '"outcome":"skipped"'
```
