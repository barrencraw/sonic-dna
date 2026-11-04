# SonicDNA Chain Contract: DNA Batch Parsing & File Watching

## 1. Chain Trigger
- **Watcher Trigger:** Detection of new non-empty content in `data/raw/toSequence.txt` by the `main.py` background watcher loop or via the `--once` CLI flag.
- **Direct Trigger:** Invoking `utils.dna_ui.main()` or `utils.dna_ui.run_batch()` programmatically.

## 2. Inputs
- **`input_file`**: File located at `data/raw/toSequence.txt` containing one DNA sequence string per line.
- **`rules_folder`**: Directory located at `rules/` containing `rules_*.json` specification files.
- **`ledger_path`**: JSON store at `data/processed_ledger.json` holding idempotency records.
- **`output_folder`**: Target directory at `data/output/` storing `toSequence_parsed.json` and `toSequence_parsed.csv`.

## 3. Terminal States
- **`success`**: The DNA sequence was parsed according to matching JSON rules and appended to output sets.
- **`error`**: The DNA sequence failed rule parsing; error recorded in ledger and output files without crashing batch processing.
- **`skipped`**: The DNA sequence exists in the ledger and was skipped due to idempotency deduplication.
- **`refused`**: The batch/sequence processing was rejected or interrupted prior to completion.

## 4. Invariants
- **Deduplication Invariant:** A DNA sequence present in `processed_ledger.json` is never re-parsed or duplicated in output JSON/CSV files.
- **Atomicity Invariant:** Partial outputs are never exposed to readers. All output file updates (`toSequence_parsed.json` and `toSequence_parsed.csv`) are written to temporary files on the target filesystem, flushed, fsynced, and renamed atomically via `os.replace`.
- **Input Preservation Invariant:** If batch processing fails due to a `PersistenceError` or system crash, the input file `toSequence.txt` MUST NOT be cleared by the watcher.

## 5. Error Classes
- **`DNAProcessingError`**: Base exception class for all DNA processing errors.
- **`RuleLoadError`**: Subclass raised when rule definitions cannot be loaded or initialized from the rules directory.
- **`PersistenceError`**: Subclass raised when reading, writing, flushing, fsyncing, or replacing ledger or output files fails.

## 6. Idempotency Key Strategy
- **Key Formulation:** The exact DNA sequence string (stripped, non-empty line) serves as the primary idempotency key.
- **Ledger Storage:** Stored as top-level keys in `data/processed_ledger.json` mapping to metadata containing `terminal_outcome` and `timestamp`.

## 7. Atomicity Boundary
- Output files `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv` are generated inside a temporary directory created within `data/output/` using `tempfile.TemporaryDirectory`.
- Files are explicitly flushed (`jf.flush()`) and synchronized to disk (`os.fsync(jf.fileno())`) prior to calling `os.replace()`.
- The ledger file is saved after output files have been atomically committed.

## 8. Required Logs
- **Watcher Logs:**
  - Start: `[Watcher] Started. Monitoring data/raw/toSequence.txt for new DNA lines…`
  - Detection: `[{timestamp}] New DNA detected → running parser…`
  - Failure: `[{timestamp}][Watcher][CRITICAL] DNA processing failed: {e}`
- **Batch Parser Logs:**
  - Start: `[Batch Parser] Starting execution...`
  - Dedupe hit: `[Idempotency] key={key} dedupe_hit=True terminal_outcome={outcome}`
  - Dedupe miss: `[Idempotency] key={key} dedupe_hit=False terminal_outcome={outcome}`
  - Completion: `[OK] Processed {count} new DNA strings. Total in ledger: {total}`

## 9. Telemetry & Grep Recipes
- **Find all idempotency hits:**
  ```bash
  grep -E "\[Idempotency\] key=.* dedupe_hit=True" logs.txt
  ```
- **Find all critical DNA processing failures:**
  ```bash
  grep -E "\[Watcher\]\[CRITICAL\]" logs.txt
  ```
- **Find all successful batch processing summaries:**
  ```bash
  grep -E "\[OK\] Processed .* new DNA strings" logs.txt
  ```
