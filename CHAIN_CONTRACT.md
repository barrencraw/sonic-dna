# DNA Batch Processing Chain Contract

## 1. Trigger
- Manual or file-watcher invocation via `main.py` (watcher / `--once`) or direct call to `utils.dna_ui.run_batch()` (aliased as `main()`).

## 2. Inputs
- `toSequence.txt`: Text file located at `data/raw/toSequence.txt` containing newline-separated DNA sequences.
- `rules/`: Directory containing JSON rule specifications for parsing DNA sequences.
- `processed_ledger.json`: Ledger file located at `data/processed_ledger.json` storing deduplication and terminal processing outcome state.

## 3. Terminal States
- `SUCCESS`: Batch parsed successfully; new entries appended to output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and recorded in `processed_ledger.json`.
- `SKIPPED`: All input DNA sequences were already processed according to `processed_ledger.json`. No output file modifications occur.
- `ERROR`: Exception raised during rule loading (`RuleLoadError`), input reading (`DNAProcessingError`), or output writing (`PersistenceError`). Input file (`toSequence.txt`) is NOT cleared, preserving raw data for retries.

## 4. Invariants
- **No Torn Writes:** Output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) are written atomically via temp files, flush + fsync, and `os.replace`. Partial writes are impossible on disk crash/failure.
- **Idempotency:** A DNA sequence present in `processed_ledger.json` is never re-parsed or re-appended to output files.
- **Input Preservation on Failure:** The watcher clears `toSequence.txt` ONLY if `run_batch()` finishes without unhandled exceptions.

## 5. Error Classes
- `DNAProcessingError`: Base class for DNA pipeline errors.
- `RuleLoadError`: Raised when rules directory or JSON rule definitions cannot be loaded.
- `PersistenceError`: Raised when writing temporary files or replacing final output files fails.

## 6. Idempotency Key
- Primary key: Raw DNA sequence string (e.g., `VOL08900750712`).
- Ledger mapping: `{ "<dna_string>": { "terminal_outcome": "success" | "error: <msg>", "timestamp": "YYYY-MM-DD HH:MM:SS" } }`

## 7. Atomicity Boundary
- Output directory (`data/output/`): Temporary files created inside `data/output/tmp_XXXXXX/` and atomically renamed to `toSequence_parsed.json` and `toSequence_parsed.csv`.
- Ledger persistence (`data/processed_ledger.json`): Updated only after new DNA sequences are successfully processed.

## 8. Required Logs & Telemetry
- **Start Log:** `[Chain][Start] chain=dna_batch_parser input_file=<path>`
- **Step / Idempotency Logs:**
  - Hit: `[Idempotency] key=<key> dedupe_hit=True terminal_outcome=<outcome>`
  - Miss: `[Idempotency] key=<key> dedupe_hit=False terminal_outcome=processing`
- **End Log:** `[Chain][End] chain=dna_batch_parser processed_new=<count> total_ledger=<count>`

## 9. Telemetry & Grep Recipes
- Check idempotency hits:
  ```bash
  grep "\[Idempotency\]" logs.txt | grep "dedupe_hit=True"
  ```
- Check chain lifecycle:
  ```bash
  grep "\[Chain\]" logs.txt
  ```
