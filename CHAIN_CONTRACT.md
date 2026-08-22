# Chain Contract: DNA Batch Parsing

## Trigger
- New non-empty lines appended to `data/raw/toSequence.txt` detected by `main.py` watcher.
- Manual invocation via CLI: `python main.py --once`.
- Explicit call to `utils.dna_ui.main()` / `run_batch()`.

## Inputs
- File `data/raw/toSequence.txt` containing one raw DNA string per line.
- Rules defined in `rules/rules_*.json`.

## Terminal States
- `success`: DNA sequence parsed against matching rule and added to ledger & parsed output files.
- `error`: DNA sequence failed rule parsing; error recorded in output files & ledger.
- `skipped`: DNA sequence already exists in ledger (`dedupe_hit=True`), step skipped without re-processing.

## Invariants
- **Atomicity:** `toSequence_parsed.json` and `toSequence_parsed.csv` are updated atomically via temporary directory writes and `os.replace`. Partial/torn output files are never committed.
- **Queue Draining:** `toSequence.txt` is cleared ONLY if batch processing and persistence complete successfully without raising errors.
- **Idempotency:** A DNA string processed once will never produce duplicate records in cumulative output files or ledger.

## Error Taxonomy
- `DNAProcessingError`: Base class for batch parsing errors.
- `RuleLoadError`: Raised when rules directory or JSON rule definitions cannot be loaded.
- `PersistenceError`: Raised when writing temporary files or atomic renaming fails.

## Idempotency Key
- The raw DNA string itself (e.g. `VOL08900750712`).

## Atomicity Boundary
- Temporary directory creation under `data/output/`. Flush + `os.fsync` before `os.replace` to replace target JSON and CSV files.

## Required Logs
- Start log: `[Batch] Starting batch processing for X DNA sequences.`
- Idempotency deduplication log: `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- End log: `[OK] Processed X new DNA strings. Total in ledger: Y`

## Grep Recipes
- Search idempotency hits: `grep "dedupe_hit=True" data/output/logs` or standard stdout.
- Search batch failures: `grep "DNA processing failed" logs`
