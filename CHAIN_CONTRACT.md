# DNA Batch Parsing Chain Contract

## 1. Overview & Chain Definition
- **Chain Name:** DNA Batch Parsing Chain
- **Location:** `main.py` (Watcher & CLI runner) and `utils/dna_ui.py` (Parser execution & persistence)

---

## 2. Trigger
- **Automatic:** Watcher thread in `main.py` detecting new non-empty content in `data/raw/toSequence.txt`.
- **Manual / One-Shot:** Invoking `python main.py --once` or calling `run_batch()` programmatically.

---

## 3. Inputs
- `data/raw/toSequence.txt`: Newline-delimited text file containing raw DNA sequences (e.g. `VOL08900750712`).
- `rules/`: Directory containing JSON rule definition files (e.g. `rules_Volume.json`).
- `data/processed_ledger.json`: Persistent ledger storing processed idempotency keys and terminal states.

---

## 4. Terminal States
- **SUCCESS:** All new DNA sequences parsed and results committed atomically to output files and ledger.
- **SKIPPED:** All input DNA sequences already exist in the ledger (idempotent deduplication hit).
- **ERROR:** Processing failed due to rule loading issues, unreadable inputs, or persistence failure.

---

## 5. Invariants
1. **Atomicity (No Torn Writes):** Output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) and ledger entries are updated atomically. Partial writes or broken JSON/CSV outputs must never occur.
2. **Idempotency:** Re-submitting the same DNA sequence produces no additional side effects or duplicate rows in output stores.
3. **Queue Drainage:** The input file `toSequence.txt` is cleared if and only if the batch parser completes without throwing a `PersistenceError` or unhandled processing error.

---

## 6. Error Taxonomy
- `DNAProcessingError`: Base exception for all batch parsing domain failures.
- `RuleLoadError` (subclass of `DNAProcessingError`): Raised when rule definitions cannot be found or parsed.
- `PersistenceError` (subclass of `DNAProcessingError`): Raised when temporary file creation, write, fsync, or rename fails.

---

## 7. Idempotency Key Strategy
- **Key Definition:** The exact stripped DNA sequence string (e.g., `VOL08900750712`).
- **Deduplication Check:** Evaluated against `data/processed_ledger.json` before invoking rule parsing calculations.

---

## 8. Atomicity Boundary
1. Create a temporary folder inside `data/output/` using `tempfile.TemporaryDirectory`.
2. Write updated JSON and CSV structures into temporary files inside the temporary directory.
3. Call `flush()` and `os.fsync(file_descriptor)` on each output file to guarantee disk persistence.
4. Atomically swap temporary files to `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv` using `os.replace`.
5. Persist the updated `data/processed_ledger.json`.

---

## 9. Telemetry & Logs
Logs emit standard idempotency trace points:
- `[Watcher] Started. Monitoring data/raw/toSequence.txt for new DNA lines…`
- `[Idempotency] key=<dna> dedupe_hit=True|False terminal_outcome=<outcome>`
- `[OK] Processed <N> new DNA strings. Total in ledger: <M>`

---

## 10. Grep Recipes
- Filter idempotency hits:
  ```bash
  grep "dedupe_hit=True" logs.txt
  ```
- Filter processing outcomes:
  ```bash
  grep "terminal_outcome=" logs.txt
  ```
- Check watcher errors:
  ```bash
  grep "\[Watcher\]\[CRITICAL\]" logs.txt
  ```
