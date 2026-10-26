# Chain Contract: DNA Batch Parsing

## Overview
The **DNA Batch Parsing Chain** consumes raw DNA sequences from `data/raw/toSequence.txt`, parses sound properties using configured rules, and atomically updates cumulative outputs and ledger tracking.

## Trigger
- **Automated:** `main.py` watcher loop detecting new non-empty content in `data/raw/toSequence.txt`.
- **Manual/Batch:** CLI execution via `python main.py --once` or `utils/dna_ui.py`.

## Inputs
- `data/raw/toSequence.txt`: UTF-8 encoded text file with one raw DNA sequence per line.
- `rules/*.json`: Rule definitions for DNA sequence parsing.
- `data/processed_ledger.json`: Existing ledger storing previously processed idempotency keys and terminal states.

## Terminal States
- `success`: DNA sequence parsed and written to output JSON and CSV without errors.
- `error`: DNA sequence failed rule parsing; error record appended to output JSON/CSV and ledger marked with error outcome.
- `skipped`: DNA sequence already present in `processed_ledger.json` (deduplication hit).

## Invariants
1. **Atomicity:** `toSequence_parsed.json` and `toSequence_parsed.csv` are updated together atomically via temporary staging files and `os.replace`. Partial writes never occur.
2. **Deduplication / Idempotency:** Duplicate DNA sequences present in `processed_ledger.json` are skipped and never re-written to cumulative stores.
3. **Queue Preservation:** `toSequence.txt` is cleared ONLY after `run_batch()` finishes successfully. On parsing/persistence errors, `toSequence.txt` remains intact for retry.

## Error Classes
- `DNAProcessingError`: Base exception for batch processing issues.
- `RuleLoadError`: Raised when JSON rule definitions cannot be loaded or parsed.
- `PersistenceError`: Raised when staging, syncing, or replacing output files fails.

## Idempotency Key Strategy
- **Key Definition:** The exact raw stripped DNA sequence string (e.g., `VOL08900750712`).
- **Storage:** `data/processed_ledger.json` maps each key to `{ terminal_outcome, timestamp }`.

## Atomicity Boundary
- Staging directory created under `data/output/.tmp_*`.
- Staging files `output.json` and `output.csv` flushed & fsynced.
- Commit via `os.replace` into `data/output/toSequence_parsed.json` and `toSequence_parsed.csv`.
- Ledger update saved after atomic replace completes.

## Required Telemetry Logs
- Log `[Idempotency] key=<DNA_KEY> dedupe_hit=<True|False> terminal_outcome=<OUTCOME>` for each processed sequence.
- Log `[OK] Processed <COUNT> new DNA strings. Total in ledger: <TOTAL>` upon successful batch completion.

## Grep Recipes
- Check deduplication hits: `grep "dedupe_hit=True" data/output/` or terminal stdout logs.
- Trace processing errors: `grep "terminal_outcome=error" data/processed_ledger.json`.
