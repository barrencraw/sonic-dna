# Chain Contract: DNA Batch Processing

## 1. Overview
The DNA Batch Processing chain is responsible for reading raw DNA sequences from an input file, parsing them according to registered rules, and persisting the results into cumulative JSON and CSV formats while maintaining an idempotency ledger.

## 2. Trigger
- **Watcher (`main.py`)**: File system change detected when `data/raw/toSequence.txt` contains new, non-empty content.
- **Manual (`main.py --once`)**: One-time execution reading all content in `toSequence.txt`.

## 3. Inputs
- `data/raw/toSequence.txt`: Plain text file containing one DNA string per line.
- `rules/*.json`: Rule definitions for the `DNACalculator`.
- `data/processed_ledger.json`: Historical record of processed DNA strings for idempotency.
- `correlation_id`: Unique string (UUID) for tracing execution.
- `actor_id`: Identifier of the entity triggering the batch (default: "system").

## 4. Terminal States
- **SUCCESS**: All new DNA strings parsed and recorded in the ledger; output files updated; input file cleared (if via watcher).
- **ERROR**: Infrastructure failure (e.g., Disk Full) or critical rule loading failure. Input file is NOT cleared.
- **SKIPPED**: DNA string already exists in the ledger with a terminal outcome (deduplication hit).
- **PARTIAL (Parse Errors)**: Individual sequence parsing errors are captured in output files and ledger with terminal outcome `error: <message>`.

## 5. Invariants
- **No Overwrite Without New Data**: Output files and ledger are only updated if at least one new DNA string is processed.
- **Atomic Multi-File Commit**: JSON output, CSV output, and Ledger are committed as a single logical transaction using temporary files and atomic renames (`os.replace`).
- **No Silent Drains**: Input file (`toSequence.txt`) is only cleared if the batch execution and atomic commit succeed without exception.
- **Idempotency**: A DNA string present in the ledger with a terminal outcome is never re-processed.

## 6. Error Classes
- `RuleLoadError`: Rules folder missing or corrupted.
- `RuleParseError`: DNA string does not match any rule or is malformed.
- `PersistenceError`: Failed to write to temporary files or perform atomic renames.
- `DNAProcessingError`: Generic base for processing failures.

## 7. Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## 8. Atomicity Boundary
- The atomic creation and replacement of:
  - `data/output/toSequence_parsed.json`
  - `data/output/toSequence_parsed.csv`
  - `data/processed_ledger.json`

## 9. Required Logs (Structured)
- Prefix: `JSON_LOG:`
- Mandatory Fields: `timestamp` (ISO 8601 UTC), `correlation_id`, `step`, `outcome`.
- Optional/Context Fields: `latency_ms`, `idempotency_key`, `dedupe_hit`, `terminal_outcome`, `input_count`, `new_processed_count`.

## 10. Telemetry Grep Recipes
- View all structured telemetry entries:
```bash
grep 'JSON_LOG:' app.log | sed 's/.*JSON_LOG: //' | jq '.'
```
- Filter by specific correlation ID:
```bash
grep '<correlation_id>' app.log | grep 'JSON_LOG:' | sed 's/.*JSON_LOG: //' | jq -s '.'
```
