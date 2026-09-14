# Chain Contract: DNA Batch Parsing

## Overview
The DNA Batch Parsing chain is responsible for reading raw DNA sequence strings from `data/raw/toSequence.txt`, parsing them against modular JSON rules, persisting flattened output into JSON and CSV files, and tracking processed sequences in a ledger.

## Trigger
- Background file watcher in `main.py` detecting non-empty content in `data/raw/toSequence.txt`.
- Manual single-run execution via CLI: `python main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: Text file containing one stripped, non-empty DNA sequence string per line (e.g., `VOL08900750712`).
- Rule files in `rules/`: JSON rules defining prefix, sub-variable structures, padding, and constraints.

## Terminal States
- `success`: DNA sequence parsed successfully against matching rule and persisted to JSON, CSV, and ledger.
- `error`: DNA sequence failed rule parsing (`RuleParseError`); error record persisted to JSON, CSV, and ledger.
- `skipped`: DNA sequence already exists in `data/processed_ledger.json` (`dedupe_hit=True`); no redundant processing performed.

## Invariants
1. **Idempotency**: Processing the same DNA sequence multiple times yields identical ledger state without duplicating entries in `toSequence_parsed.json` or `toSequence_parsed.csv`.
2. **Atomicity Boundary**: Output JSON/CSV files and ledger updates are created in temporary directory staging files, flushed/synced to disk, and moved into place via atomic `os.replace()`. Partial/torn writes are impossible.
3. **Queue Draining**: Input file `toSequence.txt` is cleared ONLY when `run_batch()` succeeds completely. On processing failure, the input file remains untouched for retry.

## Error Taxonomy
- `DNAProcessingError`: Base exception for all batch parsing failures.
- `RuleLoadError` (subclasses `DNAProcessingError`): Raised when rules directory or rule JSON definitions cannot be loaded.
- `PersistenceError` (subclasses `DNAProcessingError`): Raised when staging output files or performing atomic renames fails.

## Idempotency Key Strategy
- **Key**: Raw DNA sequence string (`dna_str`).
- **Storage**: `data/processed_ledger.json` key-value dictionary recording `terminal_outcome` and processing `timestamp`.

## Required Telemetry Logs
- `[Idempotency] key=<DNA_STR> dedupe_hit=False terminal_outcome=processing`
- `[Idempotency] key=<DNA_STR> dedupe_hit=True terminal_outcome=<OUTCOME>`
- `[OK] Processed <COUNT> new DNA strings. Total in ledger: <TOTAL>`

## Grep Recipes
- Check deduplication hits:
  ```bash
  grep "dedupe_hit=True" main.log
  ```
- Check processing errors and failures:
  ```bash
  grep -E "(CRITICAL|ERROR|PersistenceError)" main.log
  ```
- Trace idempotency log output:
  ```bash
  grep "\[Idempotency\]" main.log
  ```
