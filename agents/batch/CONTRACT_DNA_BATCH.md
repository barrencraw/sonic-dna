# DNA Batch Parser Contract

## Goal
Ensure exactly-once processing of DNA sequences from a batch input file with atomic commitment of all side effects.

## Trigger
- Watcher in `main.py` detects changes in `data/raw/toSequence.txt`.
- Explicit CLI invocation via `python main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA string per line.

## Terminal States
- `SUCCESS`: DNA sequence parsed and results committed to JSON, CSV, and Ledger.
- `PARSE_ERROR`: DNA sequence failed to parse; error recorded in JSON, CSV, and Ledger.
- `SKIPPED`: DNA sequence already exists in the Ledger and was not re-processed.

## Invariants
- If a DNA string is in the `processed_ledger.json`, its results MUST be in `toSequence_parsed.json` and `toSequence_parsed.csv`.
- The input file `toSequence.txt` is only cleared if the batch processing completes without fatal errors.
- Side effects (JSON, CSV, Ledger updates) are committed atomically.

## Error Classes
- `RuleLoadError`: Failed to load JSON rules from the `rules/` directory.
- `PersistenceError`: Failed to write output files or update the ledger atomically.
- `DNAProcessingError`: Generic base class for processing failures.

## Idempotency
- **Key**: The raw DNA string (e.g., `VOL08900750712`).
- **Store**: `data/processed_ledger.json`.

## Atomicity Boundary
- All outputs (`toSequence_parsed.json`, `toSequence_parsed.csv`) and the `processed_ledger.json` must be updated together.
- Implementation uses a temporary directory + `os.replace` for data files.

## Required Logs
- Format: `[Idempotency] key=<DNA> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `outcome` must be one of: `success`, `error: <message>`, or `skipped`.

## Telemetry Grep Recipes

### Find all failed parses
```bash
grep "terminal_outcome=error" logs/dna_batch.log
```

### Check for deduplication hits
```bash
grep "dedupe_hit=True" logs/dna_batch.log
```

### Get total processed count in last run
```bash
grep "Processed [0-9]* new DNA strings" logs/dna_batch.log
```
