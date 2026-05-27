# Contract: DNA Batch Parsing

## Goal
Successful, idempotent batch processing where JSON, CSV, and the Ledger are committed atomically, with no torn writes or duplicated entries.

## Chain Specification

### Trigger
- **Watcher (`main.py`)**: Triggered by changes to `data/raw/toSequence.txt`.
- **CLI (`main.py --once`)**: Manual execution.

### Inputs
- File: `data/raw/toSequence.txt`
- Content: One DNA string per line (e.g., `VOL08900750712`).

### Terminal States (TerminalOutcome)
- `SUCCESS`: Sequence parsed and added to outputs.
- `PARSE_ERROR`: Sequence failed validation or parsing; error recorded.
- `SKIPPED`: Sequence already exists in the ledger (Idempotency hit).

### Invariants
- **Consistency**: `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` must always be in sync.
- **Atomicity**: Either all outputs (JSON, CSV, Ledger) are updated, or none are (on a per-batch basis).
- **Drainage**: `toSequence.txt` is only cleared by the Watcher if the batch processing completes without raising an exception.

### Error Classes
- `DNAProcessingError`: Generic processing failure.
- `RuleLoadError`: Failure to load JSON rules from the `rules/` directory.
- `PersistenceError`: Failure to write or move output files.

### Idempotency
- **Key**: The raw DNA string.
- **Mechanism**: Check `processed_ledger.json` before processing.

### Telemetry / Logs
Each sequence processing must log:
`[Idempotency] key=<DNA> dedupe_hit=<True|False> terminal_outcome=<SUCCESS|PARSE_ERROR|SKIPPED>`

## Telemetry Grep Recipes

### Identify failed parses
```bash
grep "terminal_outcome=error" logs/dna_batch.log
```

### Track batch progress
```bash
grep "new DNA strings" logs/dna_batch.log
```

### Check deduplication hits
```bash
grep "dedupe_hit=True" logs/dna_batch.log
```
