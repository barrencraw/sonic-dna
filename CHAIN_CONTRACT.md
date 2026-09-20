# Mini Chain Contract: DNA Batch Processing Chain

## 1. Trigger
- Background file watcher loop in `main.py` detecting non-empty content in `data/raw/toSequence.txt`.
- Manual/CLI execution via `python main.py --once` or programmatic calls to `utils.dna_ui.main()` / `run_batch()`.

## 2. Inputs
- Input queue file: `data/raw/toSequence.txt` containing line-delimited DNA strings (e.g., `VOL08900750712`).
- Rules folder: `rules/` containing JSON rule definitions for DNA calculation (`rules_*.json`).
- Processed ledger: `data/processed_ledger.json` storing historical processing records.
- Existing JSON output: `data/output/toSequence_parsed.json`.
- Existing CSV output: `data/output/toSequence_parsed.csv`.

## 3. Terminal States
- `SUCCESS`: All non-empty DNA strings in the batch are processed and recorded in the ledger and output stores.
- `SKIPPED`: All input DNA strings were already present in `processed_ledger.json` and deduplicated (zero new writes executed).
- `FAILED`: Processing or persistence failed with a typed exception (`DNAProcessingError`, `RuleLoadError`, or `PersistenceError`). No output stores are mutated and `toSequence.txt` is NOT cleared.

## 4. Invariants
- **Atomicity**: Either all newly processed DNA results are atomically written to both `toSequence_parsed.json` and `toSequence_parsed.csv` and saved to `processed_ledger.json`, or none are.
- **Idempotency**: Processing the same DNA string multiple times yields identical ledger entries and produces no duplicate records in output stores.
- **No Silent Data Loss**: If batch processing fails during execution or persistence, the input file (`toSequence.txt`) is preserved for retry/investigation.

## 5. Error Classes
- `DNAProcessingError`: Base exception for all DNA pipeline failures.
- `RuleLoadError`: Subclass of `DNAProcessingError`, raised when rule JSON files cannot be loaded.
- `PersistenceError`: Subclass of `DNAProcessingError`, raised when atomic temp file operations or renames fail.

## 6. Idempotency Key
- The stripped DNA string itself (e.g. `VOL08900750712`).

## 7. Atomicity Boundary
- Staging directory under `data/output/` using `tempfile.TemporaryDirectory`.
- Temporary `output.json` and `output.csv` files are written, flushed (`jf.flush()`), and synced to disk (`os.fsync(jf.fileno())`).
- Atomic rename commit via `os.replace` to `toSequence_parsed.json` and `toSequence_parsed.csv`.
- Ledger saved to `data/processed_ledger.json`.
- Input file `data/raw/toSequence.txt` cleared only upon full batch success in caller.

## 8. Required Telemetry / Logs
- **Start Log**: `[BatchParser][START] input_file={path} total_lines={count}`
- **Step / Idempotency Log**: `[Idempotency] key={key} dedupe_hit={True/False} terminal_outcome={outcome}`
- **End Log**: `[BatchParser][END] processed={new_count} total_ledger={total_count}`

## 9. Grep Recipe
```bash
# View all batch processing telemetry
grep -E '\[(BatchParser|Idempotency)\]' data/logs.txt

# Inspect deduplicated hits vs new executions
grep 'dedupe_hit=True' data/logs.txt
grep 'dedupe_hit=False' data/logs.txt
```
