# Chain Contract: DNA Batch Parsing

## 1. Overview
The DNA Batch Parsing chain reads raw DNA sequence strings from disk, parses them according to rule definitions, records their terminal execution states in an idempotency ledger, and atomically commits structured JSON and CSV outputs.

## 2. Trigger
- **File System Event / Watcher Loop (`main.py:watch_loop`)**: Non-empty modification to `data/raw/toSequence.txt`.
- **Manual CLI Command (`main.py:process_once`)**: Direct one-time invocation via `python main.py --once`.
- **Programmatic Invocation**: `utils.dna_ui.run_batch(correlation_id=None)` or alias `main()`.

## 3. Inputs
- Input file: `data/raw/toSequence.txt` containing one DNA sequence string per line (e.g. `VOL08900750712`).
- Optional context: `correlation_id` (str) for distributed tracing, defaults to a generated UUID4 string.

## 4. Terminal States
- **`SUCCESS`**: DNA sequence was successfully parsed according to its rule definition, appended to output collections, and registered in the ledger.
- **`ERROR`**: DNA sequence failed validation/parsing (e.g., `RuleParseError`), error details recorded in output files, and recorded in the ledger with outcome `error: <msg>`.
- **`SKIPPED`**: DNA sequence was previously processed and exists in `data/processed_ledger.json` (`dedupe_hit=True`), skipping parsing and side-effect output writes.

## 5. Invariants
1. **Idempotency**: Processing the same DNA sequence multiple times results in exactly one entry in the cumulative JSON and CSV outputs.
2. **Atomicity**: Either all outputs (`toSequence_parsed.json`, `toSequence_parsed.csv`, and `data/processed_ledger.json`) are updated successfully on disk, or none are updated. No partial or corrupt file states.
3. **Queue Draining Safety**: The input queue file (`data/raw/toSequence.txt`) is truncated **only** after `run_batch` returns successfully. If an error or crash occurs during processing or atomic commit, the input file remains untouched.
4. **No Double Writes**: File persistence operations only trigger when new non-deduplicated items have been processed (`new_processed_count > 0`).

## 6. Error Taxonomy
- `DNAProcessingError`: Root exception for all batch parsing issues.
  - `RuleLoadError`: Raised when rule JSON configurations cannot be located or loaded from disk.
  - `PersistenceError`: Raised when reading input, writing temporary files, syncing, or committing final outputs fails.
    - `AtomicWriteError`: Specific failure during atomic temporary file operations.
    - `LedgerSaveError`: Specific failure saving the processed ledger atomically.
- `RuleParseError`: Raised when an individual DNA sequence syntax does not conform to the active rule schemas (caught per-sequence and registered as terminal `error` in outputs).

## 7. Idempotency Key Strategy
- **Key**: Stripped DNA sequence string (e.g., `VOL08900750712`).
- **Store**: `data/processed_ledger.json`.
- **Structure**:
  ```json
  {
    "VOL08900750712": {
      "terminal_outcome": "success",
      "timestamp": "2026-03-02 10:15:00",
      "correlation_id": "b0a2f5..."
    }
  }
  ```

## 8. Atomicity Boundary
1. Read `data/raw/toSequence.txt` and load existing `data/processed_ledger.json`, `toSequence_parsed.json`, and `toSequence_parsed.csv`.
2. Process all pending DNA sequences and accumulate new entries in-memory.
3. If new entries were processed:
   a. Create temporary files in `data/output/` (same filesystem to ensure rename atomicity).
   b. Write JSON and CSV to temp files, `flush()`, and execute `os.fsync()`.
   c. Atomically replace final files using `os.replace()`.
   d. Atomically write/replace `data/processed_ledger.json`.
4. Return success to caller (`main.py`), which then safely truncates `data/raw/toSequence.txt`.

## 9. Required Logs (Structured Telemetry)
All logs emitted by the chain include:
- `timestamp`: UTC ISO 8601 formatted string.
- `correlation_id`: Unique tracing ID for the batch invocation.
- `chain_name`: `"dna_batch_parser"`.
- `step`: Lifecycle phase (`START`, `DEDUPE`, `PARSE`, `PERSIST`, `COMPLETE`).
- `outcome`: Status of step (`ok`, `dedupe_hit`, `dedupe_miss`, `error`).
- `latency_ms`: Elapsed time in milliseconds from start to current step.
- `idempotency_key`: DNA sequence string (for sequence-level steps).

## 10. Grep Recipes
- Search for batch execution by correlation ID:
  ```bash
  grep 'correlation_id=<CORRELATION_ID>' logs/*.log
  ```
- Find all deduplication hits:
  ```bash
  grep 'dedupe_hit=True' logs/*.log
  ```
- Find batch persistence failures:
  ```bash
  grep 'step=PERSIST' logs/*.log | grep 'outcome=error'
  ```
