# CHAIN CONTRACT: DNA Batch Parsing

## Overview
The DNA Batch Parsing chain is responsible for consuming raw DNA sequence inputs, parsing them according to JSON variable rulesets, maintaining an idempotent processing ledger, and persisting structured outputs atomically.

---

## 1. Trigger
- **CLI Trigger:** `python main.py --once`
- **Daemon/Watcher Trigger:** Background thread in `main.py` observing modifications to `data/raw/toSequence.txt`.
- **Direct Invocation:** Direct execution of `run_batch(correlation_id=None)` in `utils/dna_ui.py`.

---

## 2. Inputs
- `data/raw/toSequence.txt`: Newline-delimited file containing unparsed DNA sequences (e.g., `VOL08900750712`).
- `rules/*.json`: Variable rules defining prefix, subvariable specs, pad lengths, and min/max ranges (e.g. `rules_Volume.json`).
- `data/processed_ledger.json`: State ledger recording processed idempotency keys and terminal states.

---

## 3. Terminal States
1. **`SUCCESS`**: All new DNA sequences parsed, `toSequence_parsed.json` and `toSequence_parsed.csv` updated atomically, ledger updated, and `toSequence.txt` cleared.
2. **`SKIPPED`**: All input DNA sequences already exist in `processed_ledger.json`. Output files remain untouched, and `toSequence.txt` is cleared.
3. **`FAILURE`**: Exception encountered (e.g., `RuleLoadError`, `DNAProcessingError`, `PersistenceError`). Output files and ledger are NOT corrupted (rolled back/unmodified), and `toSequence.txt` is NOT cleared.

---

## 4. Invariants
- **Atomicity Boundary:** Temporary files are flushed, fsynced, and renamed into place using `os.replace`. Partial writes or torn JSON/CSV files are strictly prevented.
- **Idempotency Guarantee:** Sequences present in `processed_ledger.json` are skipped. Re-invoking with the same inputs produces identical output without duplicating entries.
- **No Silent Drains:** `toSequence.txt` is cleared ONLY when `run_batch()` returns cleanly without raising errors.

---

## 5. Error Taxonomy
- `DNAProcessingError`: Base class for all DNA batch parsing errors.
  - `RuleLoadError`: Raised when JSON rule definitions cannot be loaded or parsed.
  - `PersistenceError`: Raised when writing temporary files or performing atomic renames fails.
- `RuleParseError`: Raised when an individual DNA sequence fails variable pattern validation (recorded as an error entry in output).

---

## 6. Idempotency Key Strategy
- **Key Format:** The raw DNA sequence string (e.g., `VOL08900750712`).
- **Ledger Schema:**
  ```json
  {
    "VOL08900750712": {
      "terminal_outcome": "success",
      "timestamp": "2025-06-02 12:00:00"
    }
  }
  ```

---

## 7. Required Telemetry Logs
All operations emit structured log lines with the `[DNA_BATCH]` prefix containing:
- `timestamp`: UTC ISO / formatted timestamp
- `correlation_id`: Unique invocation ID
- `step`: `START`, `DEDUPE`, `PARSE`, `COMMIT`, `END`, or `ERROR`
- `idempotency_key`: DNA sequence string (where applicable)
- `outcome`: State indicator (`processing`, `success`, `skipped`, `error`)

---

## 8. Telemetry Grep Recipes
```bash
# Filter all DNA Batch chain telemetry
grep "\[DNA_BATCH\]" app.log

# Track processing of a specific DNA sequence key
grep "\[DNA_BATCH\]" app.log | grep "key=VOL08900750712"

# Monitor errors across batch runs
grep "\[DNA_BATCH\]" app.log | grep "step=ERROR"
```
