# DNA Batch Parsing & Persistence Chain Contract

## 1. Trigger
- **Manual/CLI invocation:** Executing `python main.py --once` to perform a one-time batch parse of input DNA strings.
- **Background File Watcher:** The directory watcher loop in `main.py` detects non-empty, new contents in `data/raw/toSequence.txt`, automatically triggering the batch parser.

## 2. Inputs
- A text file located at `data/raw/toSequence.txt` containing one DNA sequence per line.
- The existing processed sequence ledger at `data/processed_ledger.json`.
- Rules definition files (JSON) under the `rules/` directory.

## 3. Terminal States
- **SUCCESS:** The input file is read, all non-duplicate DNA strings are successfully parsed against rules, the results are committed to `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`, the ledger is updated, and the input file is safely cleared.
- **PARTIAL ERROR (SKIPPED/LOGGED):** Non-duplicate DNA strings with rule syntax/parse errors are caught, appended to output JSON and CSV as error entries, updated in the ledger as `error: <message>`, and the batch run continues.
- **FAILURE (ABORTED):** A critical system error (e.g., file system permission issues, rule loading failure, or disk space exhaustion) occurs during loading, parsing, or file writing. No changes are committed to the output files or ledger on disk, the input file is NOT cleared, and a clean exception is raised.

## 4. Invariants
- **No Torn Writes:** If any output file write (JSON, CSV, or ledger) fails during the batch commit, the entire transaction is aborted, and all three files remain unchanged from their pre-transaction states.
- **Consolidated Ledger and Output Sync:** The ledger and output files (JSON/CSV) must always remain perfectly in sync. Every successfully parsed or skipped DNA string in the output files must have an corresponding entry in the ledger.
- **Zero-State safety:** If `toSequence.txt` contains zero new DNA strings (all already processed or empty file), no disk writes to JSON/CSV or the ledger are executed.

## 5. Error Classes
- `RuleLoadError`: Raised when the `DNACalculator` fails to load rule files during initialization.
- `RuleParseError`: Raised per sequence when a DNA sequence does not match the rules.
- `PersistenceError`: Raised when there is a physical failure to write or replace output/ledger files.

## 6. Idempotency Key
- The **DNA sequence string** itself (e.g., `VOL08900750712`) is the unique idempotency key.
- If a sequence is present in the ledger with a terminal state, it is skipped in all future batch parse iterations.

## 7. Atomicity Boundary
- The atomicity boundary covers the entire persistence phase of `utils/dna_ui.py`.
- **Pre-commit:** All processed inputs are written to temporary files (`output.json.tmp`, `output.csv.tmp`, `ledger.json.tmp`) inside the output/data directories.
- **Commit:** Files are flushed and synchronized to disk via `fsync()`, then atomically replaced using `os.replace()`.
- **Post-commit:** The original input file `toSequence.txt` is cleared by the watcher/once-runner only after a successful commit.

## 8. Required Logs
- **Start Log:** `[Batch] Starting batch parsing of <N> DNA sequences.`
- **Deduplication Check Log:** `[Idempotency] key=<DNA> dedupe_hit=<True/False> terminal_outcome=<outcome>`
- **Completion Log:** `[Batch] Successfully committed <N> new DNA sequences to outputs. Total in ledger: <Total>.`

## 9. Grep Recipes for Log Inspection
- **Inspect batch execution lifecycle:**
  ```bash
  grep -E "\[Batch\]|\[Idempotency\]" stdout.log
  ```
- **Track unique processed items and deduplication hits:**
  ```bash
  grep -E "dedupe_hit=(True|False)" stdout.log
  ```
- **Check for successful commits:**
  ```bash
  grep "Successfully committed" stdout.log
  ```
