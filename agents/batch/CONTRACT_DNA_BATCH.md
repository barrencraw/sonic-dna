# Chain Contract: DNA Batch Parser

## Trigger
- `data/raw/toSequence.txt` is updated (Watcher in `main.py`).
- `main.py --once` is executed manually or via automation.

## Inputs
- `data/raw/toSequence.txt`: A plain text file containing one DNA string per line.
- `rules/`: Directory containing JSON rulesets for DNA parsing.

## Terminal States
- **SUCCESS**: All DNA strings in the input file were processed (either parsed or recorded as errors) and the output files were updated.
- **PARTIAL**: Some DNA strings failed parsing, but the system recorded these failures in the ledger and output files, continuing with other strings.
- **FAILURE**: A `PersistenceError` or `RuleLoadError` occurred, preventing any updates to the output files or ledger.

## Invariants
- **Idempotency**: DNA strings already present in `data/processed_ledger.json` are skipped to avoid redundant computation and duplicate entries.
- **Atomicity**: `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` are updated as a single logical transaction using the temporary directory + atomic rename pattern.
- **Input Drain**: `toSequence.txt` is only cleared if the processing and atomic commit succeed.

## Error Classes
- `DNAProcessingError`: Base class for parser-related issues.
- `RuleLoadError`: Rules could not be loaded from the `rules/` directory.
- `PersistenceError`: Failed to write or rename output files atomically.

## Required Logs
- `[Idempotency] key=<DNA> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `[OK] Processed <count> new DNA strings.`

## Telemetry Check: Grep Recipe
To verify processing outcomes:
```bash
grep "Idempotency" logs.txt | cut -d' ' -f2,3,4
```
To check for persistence failures:
```bash
grep "PersistenceError" logs.txt
```
