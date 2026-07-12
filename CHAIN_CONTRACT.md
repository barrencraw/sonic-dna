# Chain Contract: DNA Batch Processing

## Trigger
- **Watcher (`main.py`)**: File system change detected in `data/raw/toSequence.txt`.
- **Manual (`main.py --once`)**: Direct execution for one-time processing.

## Inputs
- `data/raw/toSequence.txt`: A plain text file containing one DNA string per line.
- `rules/*.json`: Rule definitions for the `DNACalculator`.
- `data/processed_ledger.json`: Historical record of processed DNA strings for idempotency.

## Terminal States
- **SUCCESS**: All new DNA strings parsed and recorded in the ledger; output files updated; input file cleared (if via watcher).
- **ERROR**: Infrastructure failure (e.g., Disk Full) or critical rule loading failure. Input file is NOT cleared.
- **PARTIAL (Refused)**: Thermal lockout (if implemented) or individual parse errors. Parse errors are recorded in output files and ledger as `error`.

## Invariants
- **No Overwrite Without New Data**: Output files are only updated if at least one new DNA string is processed.
- **Atomicity**: The JSON output, CSV output, and Ledger are updated as a single logical transaction using atomic renames.
- **Idempotency**: A DNA string present in the ledger with a terminal outcome (success or error) is never re-processed.

## Error Classes
- `RuleLoadError`: Rules folder missing or corrupted.
- `RuleParseError`: DNA string does not match any rule or is malformed.
- `PersistenceError`: Failed to write to temporary files or perform atomic renames.
- `DNAProcessingError`: Generic base for processing failures.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- The writing and renaming of:
    - `data/output/toSequence_parsed.json`
    - `data/output/toSequence_parsed.csv`
    - `data/processed_ledger.json`

## Required Logs (Structured)
- Prefix: `JSON_LOG:`
- Mandatory Fields: `timestamp`, `correlation_id`, `step`, `outcome`, `latency_ms`.
- Optional: `idempotency_key`, `dedupe_hit`.

## Telemetry Grep Recipe
```bash
grep "JSON_LOG:" logs.txt | jq '.'
```
