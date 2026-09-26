# Chain Contract: DNA Batch Parsing

## 1. Chain Identification
- **Chain Name:** DNA Batch Parsing Chain
- **Primary Modules:** `main.py` (watcher / once runner), `utils/dna_ui.py` (parser execution)

## 2. Trigger
- Appending new DNA sequence lines to `data/raw/toSequence.txt` (via watcher thread) OR explicit invocation via CLI (`python main.py --once`).

## 3. Inputs
- `data/raw/toSequence.txt`: Text file containing 1..N raw DNA sequences (one per line).
- `rules/*.json`: Predefined rule definitions for parsing SonicDNA attributes.
- `data/processed_ledger.json`: Persistent ledger tracking previously processed idempotency keys.

## 4. Terminal States
- **SUCCESS:** All new DNA sequences in `toSequence.txt` were successfully parsed or deduplicated, cumulative JSON/CSV output files were atomically replaced on disk, the ledger was saved, and `toSequence.txt` was truncated.
- **SKIPPED (Deduplicated):** Sequences already existing in `data/processed_ledger.json` are skipped without side effects or redundant processing.
- **FAILURE (Terminal Error):** Rule parsing error (`RuleParseError`) records an error entry in JSON/CSV and ledger marked with terminal outcome `error: <reason>`.
- **FAILURE (Infrastructure/Persistence Error):** I/O or filesystem failure throws `PersistenceError` or `DNAProcessingError`. Outputs remain untouched and `toSequence.txt` is NOT cleared.

## 5. Invariants
- **Atomicity:** `toSequence_parsed.json` and `toSequence_parsed.csv` are never left in a partially-written or corrupt state on disk. Writes are staged in a temp folder and atomically renamed via `os.replace`.
- **No Data Loss on Failure:** If processing or persistence fails mid-batch, `toSequence.txt` is not truncated, allowing retries on the next watcher loop or execution.
- **Idempotency:** Re-submitting an identical DNA string does not duplicate rows in output files or overwrite prior success entries in the ledger.

## 6. Error Taxonomy
- `DNAProcessingError`: Base exception for all batch parsing domain errors.
- `RuleLoadError` (subclass of `DNAProcessingError`): Raised when rules directory fails to load.
- `PersistenceError` (subclass of `DNAProcessingError`): Raised when atomic staging/writing or renaming fails.

## 7. Idempotency Key Strategy
- **Key Definition:** The exact raw DNA sequence string (e.g. `VOL08900750712`).
- **Store:** `data/processed_ledger.json` key-value dictionary mapping `idempotency_key` -> `{ 'terminal_outcome': <str>, 'timestamp': <str> }`.

## 8. Atomicity Boundary
- **Boundary Scope:** All filesystem output mutations (`toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json`).
- **Commit Mechanism:** Staging outputs inside `tempfile.TemporaryDirectory(dir=output_folder)`, calling `jf.flush()` and `os.fsync(jf.fileno())`, followed by atomic `os.replace`.

## 9. Required Logs
- `[Idempotency] key=<key> dedupe_hit=True terminal_outcome=<outcome>`
- `[Idempotency] key=<key> dedupe_hit=False terminal_outcome=<outcome>`
- `[OK] Processed <N> new DNA strings. Total in ledger: <M>`

## 10. Grep Recipes
- Search for deduplication hits:
  `grep "dedupe_hit=True" logs.log`
- Search for idempotency execution logs:
  `grep "\[Idempotency\]" logs.log`
- Search for parsing persistence failures:
  `grep "PersistenceError" logs.log`
