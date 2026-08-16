# Chain Contract: DNA Batch Parsing Chain

## 1. Overview & Trigger
- **Chain Name:** DNA Batch Parsing (`utils/dna_ui.py:run_batch` / `main.py`)
- **Trigger:**
  - Automated file watcher (`main.py`) detecting non-empty content appended to `data/raw/toSequence.txt`.
  - On-demand execution via `python main.py --once` or direct function call `utils.dna_ui.run_batch()`.

---

## 2. Inputs
- **Primary Input File:** `data/raw/toSequence.txt` (Contains stripped, non-empty DNA sequence strings, one per line).
- **Rule Definitions:** JSON files in `rules/` (e.g., `rules_Volume.json`, `rules_Timbre.json`).
- **Ledger State:** `data/processed_ledger.json` (Stores idempotency keys and terminal outcomes).
- **Existing Outputs:** `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`.

---

## 3. Terminal States
- **SUCCESS:** All new DNA sequences parsed, appended to JSON/CSV, saved to ledger, and `toSequence.txt` safely cleared by watcher.
- **SKIPPED (Deduplicated):** Input sequence already present in `processed_ledger.json` with a terminal outcome; skipped with zero side effects.
- **ERROR (Handled / Parse Error):** DNA sequence failed rule validation/parsing (`RuleParseError`); error outcome recorded in ledger and output files without aborting the batch.
- **CRITICAL FAILURE (Aborted):** I/O, Rule Loading, or Persistence error (`PersistenceError`, `RuleLoadError`, `DNAProcessingError`); processing halts immediately, atomic writes roll back temp files, and `toSequence.txt` is **NOT** cleared.

---

## 4. Invariants
1. **Atomicity Boundary:**
   - Either **ALL** newly processed entries are committed to `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json`, or **NONE** are.
   - Partial writes, corrupted output JSON/CSV, or torn ledger entries must never exist on disk.
2. **No Input Data Loss on Failure:**
   - `toSequence.txt` is cleared **ONLY** after `run_batch()` returns successfully without raising exceptions.
3. **Idempotency & Deduplication:**
   - Processing a DNA sequence with key $K$ twice yields identical state as processing $K$ once.
   - No duplicate entries in `toSequence_parsed.json` or `toSequence_parsed.csv` for the same DNA sequence key.

---

## 5. Error Taxonomy & Exceptions
- `DNAProcessingError` (Base Exception)
  - `RuleLoadError`: Rules folder unreadable or rules corrupted.
  - `PersistenceError`: Writing to temp files or atomic renaming (`os.replace`) failed.
  - `RuleParseError`: Individual DNA sequence format violation (handled per-sequence).

---

## 6. Idempotency Strategy
- **Idempotency Key:** The DNA sequence string (e.g., `VOL08900750712`).
- **Dedupe Mechanism:**
  - Read `data/processed_ledger.json` at start of batch execution.
  - Check `key in ledger`.
  - If `True`, emit `[Idempotency] key=<key> dedupe_hit=True terminal_outcome=<outcome>` and skip processing.
  - If `False`, process DNA sequence, update in-memory outputs, and record in ledger upon commit.

---

## 7. Atomicity Boundary & Implementation Pattern
- **Pattern:** Temporary Directory + Flush/Sync + Atomic Replace (`tempfile.TemporaryDirectory` + `os.fsync` + `os.replace`).
- **Steps:**
  1. Create temp directory under `data/output/`.
  2. Write updated `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` to temp directory.
  3. Call `flush()` and `os.fsync()` on file descriptors.
  4. Perform `os.replace()` to swap temp files into final locations atomically.

---

## 8. Telemetry & Required Logging
- **Deduplication Check:**
  `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- **Batch Outcome Summary:**
  `[OK] Processed <count> new DNA strings. Total in ledger: <total>`
- **Watcher Error Log:**
  `[<timestamp>][Watcher][CRITICAL] DNA processing failed: <error_message>`

---

## 9. Grep Recipes
- **Find all idempotency hits:**
  ```bash
  grep "dedupe_hit=True" logs/*.log
  ```
- **Find all batch completions:**
  ```bash
  grep "\[OK\] Processed" logs/*.log
  ```
- **Find processing failures:**
  ```bash
  grep "CRITICAL" logs/*.log
  ```
