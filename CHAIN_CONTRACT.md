# Chain Contract: DNA Batch Parsing

## 1. Overview & Scope
This contract governs the **DNA Batch Parsing** chain (`utils/dna_ui.py` triggered via `main.py` watcher or CLI `--once`).
The chain reads raw DNA sequences from `data/raw/toSequence.txt`, parses them using rules in `rules/`, persists cumulative output files (`toSequence_parsed.json` and `toSequence_parsed.csv`), and records execution outcomes in `data/processed_ledger.json`.

---

## 2. Chain Contract Specifications

### Trigger
- **Automatic (Watcher):** Background thread monitoring `data/raw/toSequence.txt` for new non-empty content.
- **Manual (CLI):** Invocation via `python main.py --once` or direct call to `utils.dna_ui.run_batch()`.

### Inputs
- **Input File:** `data/raw/toSequence.txt` containing line-delimited DNA strings (e.g., `VOL08900750712`).
- **Rules Folder:** `rules/` directory containing JSON rule definitions (e.g., `rules_Volume.json`).
- **Ledger:** `data/processed_ledger.json` storing processed idempotency keys and terminal states.

### Terminal States
- **`success`:** DNA sequence successfully matched a rule and was parsed into structured values.
- **`error: <message>`:** DNA sequence failed rule parsing (recorded in output & ledger to prevent infinite retry loops).
- **`skipped`:** DNA sequence already exists in `data/processed_ledger.json` (deduplication hit).

### Invariants
1. **Idempotency:** Re-processing the same DNA sequence returns immediately without adding duplicate entries to outputs or performing redundant calculations.
2. **Atomicity:** Partial or torn writes are impossible. Outputs (`toSequence_parsed.json` and `toSequence_parsed.csv`) are written to temporary files with `os.fsync()` and atomically swapped via `os.replace()`.
3. **Queue Draining:** Input file `data/raw/toSequence.txt` is cleared by the caller (`main.py`) **only if** `run_batch()` completes without unhandled persistence errors.
4. **Ledger Consistency:** The ledger is updated on disk only after output files are successfully committed to physical storage.

### Error Taxonomy
- `DNAProcessingError`: Base class for errors occurring during sequence loading or processing.
- `RuleLoadError` (subclass of `DNAProcessingError`): Raised when rule definitions in `rules/` fail to load.
- `RuleParseError`: Raised when a specific DNA sequence fails to conform to variable rule definitions. Handled per-sequence.
- `PersistenceError` (subclass of `DNAProcessingError`): Raised when writing or atomically committing output files fails.

### Idempotency Key
- **Key:** The exact stripped DNA string (e.g., `VOL08900750712`).
- **Storage:** Stored in `data/processed_ledger.json` under key name with `terminal_outcome` and `timestamp`.

### Atomicity Boundary
- **Boundary:** All file modifications (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`).
- **Mechanism:**
  1. Write JSON and CSV to a temporary directory under `data/output/`.
  2. Call `flush()` and `os.fsync()` on file descriptors.
  3. Atomic rename via `os.replace()`.
  4. Save updated ledger to `data/processed_ledger.json`.

### Required Logs & Telemetry
Every batch run emits structured JSON telemetry logs prefixed with `JSON_LOG:` to stdout:
- Mandatory Fields:
  - `timestamp`: UTC ISO 8601 string (e.g., `2025-09-16T13:14:15.123456+00:00`)
  - `correlation_id`: Unique trace ID (UUIDv4)
  - `actor_id`: Entity executing batch (`batch_parser` or caller ID)
  - `chain_name`: `dna_batch_parsing`
  - `step`: `start`, `dedupe_check`, `parse_sequence`, `atomic_write`, `end`
  - `outcome`: `success`, `error`, `skipped`
  - `latency_ms`: Duration of step/chain in milliseconds
  - `idempotency_key`: DNA sequence string (for sequence-level steps)
  - `outcome_detail`: Descriptive text or error string

---

## 3. Telemetry & Grep Recipes

### Inspect all structured JSON logs:
```bash
grep "JSON_LOG:" app.log
```

### Filter logs by correlation ID:
```bash
grep "JSON_LOG:" app.log | grep '"correlation_id": "<your-id>"'
```

### Trace errors in batch execution:
```bash
grep "JSON_LOG:" app.log | grep '"outcome": "error"'
```

### Inspect deduplication hits:
```bash
grep "JSON_LOG:" app.log | grep '"step": "dedupe_check"'
```
