# Chain Contract: DNA Batch Parsing

## 1. Trigger
- **Entry Points:**
  - File Watcher (`main.py` -> `watch_loop`): triggered when non-empty content is written to `data/raw/toSequence.txt`.
  - Single-Run CLI (`main.py --once`): triggered via process invocation (`process_once`).
  - Directly via Python API (`utils/dna_ui.py` -> `run_batch`).

## 2. Inputs
- `data/raw/toSequence.txt`: Newline-delimited file containing DNA strings (e.g., `VOL08900750712`).
- `rules/*.json`: Sound property rule definitions used by `DNACalculator`.
- `data/processed_ledger.json`: Persistent ledger tracking terminal outcomes per idempotency key.

## 3. Terminal States & Invariants
- **Success:**
  - All new (unprocessed) DNA sequences in `toSequence.txt` are parsed into `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`.
  - Ledger updated with `terminal_outcome: success` or `terminal_outcome: error: <details>`.
  - Output files (`.json`, `.csv`) and ledger are updated via atomic rename.
  - `data/raw/toSequence.txt` is cleared by `main.py` only upon successful completion.
- **Invariants:**
  - **No Silent Loss:** Input `toSequence.txt` is never cleared if batch execution raises an exception.
  - **Deduplication:** Repeated DNA strings present in ledger are skipped without duplicate side-effects.
  - **Atomic Commit:** Partial or torn writes to output/ledger files do not occur on disk write failures.

## 4. Error Taxonomy
- `DNAProcessingError`: Base class for all DNA domain & pipeline errors.
- `RuleLoadError`: Raised when rules directory cannot be read or parsed.
- `PersistenceError`: Raised when writing temporary files or atomic renaming fails.
- `RuleParseError`: Internal exception when a DNA string fails rule validation; captured and recorded into ledger & outputs as an error entry.

## 5. Idempotency & Atomicity Boundaries
- **Idempotency Key:** The DNA string (e.g., `VOL08900750712`).
- **Atomicity Boundary:**
  - Writing JSON and CSV to a temporary folder (`output_folder/tmp/`).
  - Syncing file descriptors (`os.fsync`) before calling `os.replace`.
  - Writing ledger update to a temporary folder (`data_folder/tmp/`) and atomically renaming to `processed_ledger.json`.

## 6. Required Log Telemetry
- Start/Processing logs: `[Idempotency] key=<DNA> dedupe_hit=<Bool> terminal_outcome=<State>`
- Completion logs: `[OK] Processed <count> new DNA strings. Total in ledger: <total>`

## 7. Grep Recipes for Observability
- Check deduplication hits:
  `grep "dedupe_hit=True" data/output/*.log 2>/dev/null`
- Trace terminal outcomes:
  `grep "terminal_outcome" data/processed_ledger.json`
- Verify errors:
  `grep "DNA processing failed" watcher.log 2>/dev/null`
