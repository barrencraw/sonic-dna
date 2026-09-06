# Chain Contract: DNA Batch Parsing

## 1. Overview
The **DNA Batch Parsing Chain** is responsible for reading raw audio DNA sequences from `data/raw/toSequence.txt`, parsing them against JSON rule definitions in `rules/`, deduplicating sequences against `data/processed_ledger.json`, and persisting structured JSON and CSV output files under `data/output/`.

---

## 2. Trigger
- **CLI Mode:** `python main.py --once` (invokes `process_once()`).
- **Watcher Loop:** Background thread in `main.py` monitoring `data/raw/toSequence.txt`.
- **Direct API:** `utils.dna_ui.run_batch()` or `utils.dna_ui.main()`.

---

## 3. Inputs
- `data/raw/toSequence.txt`: Text file containing newline-delimited raw DNA sequences (e.g. `VOL08900750712`).
- `rules/rules_*.json`: Rule specification files in `rules/` defining prefixes and variable schemas.
- `data/processed_ledger.json`: JSON ledger mapping `idempotency_key` -> `{ 'terminal_outcome': <str>, 'timestamp': <str> }`.

---

## 4. Terminal States
- `success`: Sequence parsed successfully against a matching rule and added to output.
- `error: <reason>`: Sequence failed rule parsing (`RuleParseError`); error recorded in ledger and outputs.
- `skipped`: Sequence key was already present in `processed_ledger.json` (deduplicated).

---

## 5. Invariants
1. **No Torn Writes (Atomicity):** All output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are written via temporary files, flushed/fsynced to disk, and committed atomically using `os.replace`. Partial writes on disk crash never corrupt existing outputs or ledger.
2. **Idempotency:** A sequence present in `processed_ledger.json` will never be reprocessed or duplicated in output JSON/CSV files on subsequent runs.
3. **No Silent Drains / Uncaught File Truncation:** In `main.py`, input file `toSequence.txt` is cleared ONLY if `run_batch()` completes without throwing uncaught processing exceptions (`DNAProcessingError`).

---

## 6. Error Taxonomy
- `DNAProcessingError`: Base exception class for all DNA batch parsing errors.
- `RuleLoadError` (*subclass of `DNAProcessingError`*): Raised when rule definitions in `rules/` fail to load.
- `PersistenceError` (*subclass of `DNAProcessingError`*): Raised when writing or atomically renaming output files or ledger fails.
- `RuleParseError`: Raised when a specific DNA sequence fails parsing rules.

---

## 7. Idempotency Key Strategy
- **Key:** `idempotency_key = dna_sequence.strip()`
- **Lookup:** Check if key exists in `processed_ledger.json`.
- **Storage:** Stored in `processed_ledger.json` with terminal outcome and timestamp upon successful processing.

---

## 8. Atomicity Boundary
- Output files are prepared in a temporary directory located on the same filesystem as `data/output/`.
- File handles are explicitly flushed (`jf.flush()`) and synced (`os.fsync(jf.fileno())`) before renaming.
- Swap is performed atomically using `os.replace(tmp_file, target_file)`.

---

## 9. Required Telemetry Logs
- **Batch Start:** `[BatchStart] total_sequences=<n>`
- **Sequence Step / Idempotency:**
  - On deduplication hit: `[Idempotency] key=<key> dedupe_hit=True terminal_outcome=<outcome>`
  - On new sequence process: `[Idempotency] key=<key> dedupe_hit=False terminal_outcome=<outcome>`
- **Batch End:** `[BatchEnd] processed=<count> total_ledger=<total>`

---

## 10. Grep Recipes
- **Filter Idempotency Events:**
  ```bash
  grep "\[Idempotency\]" logs.txt
  ```
- **Filter Batch Execution Lifecycle:**
  ```bash
  grep -E "\[Batch(Start|End)\]" logs.txt
  ```
- **Filter Terminal Outcome Errors:**
  ```bash
  grep "terminal_outcome=error" logs.txt
  ```
