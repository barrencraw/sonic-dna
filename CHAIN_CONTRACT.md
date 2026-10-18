# Chain Contract: DNA Batch Parsing

## Overview
The **DNA Batch Parsing Chain** processes batches of raw DNA sequence strings into parsed JSON structures and flattened CSV representations, maintaining an idempotency ledger to prevent duplicate execution and guaranteeing atomic file persistence.

---

## Contract Specification

### 1. Trigger
- **Automatic Watcher:** Detection of new non-empty content in `data/raw/toSequence.txt` by `main.py` watcher loop.
- **Manual / CLI:** Execution via `python main.py --once` or programmatic invocation of `run_batch()` in `utils/dna_ui.py`.

### 2. Inputs
- `input_path`: Path to raw input file (`data/raw/toSequence.txt`), containing one raw DNA sequence string per line.
- `rules_folder`: Directory containing rule definition JSON files (`rules/`).
- `ledger_path`: Path to idempotency ledger (`data/processed_ledger.json`).
- `correlation_id` *(optional)*: Unique trace identifier for the batch run.

### 3. Terminal States
- **Batch Outcome:**
  - `SUCCESS`: All DNA sequences processed or skipped, and outputs committed atomically.
  - `ERROR`: Unhandled I/O, rule load, or atomic rename failure.
- **Per-Sequence Terminal Outcome:**
  - `success`: DNA sequence successfully parsed according to matching rule schema.
  - `error: <message>`: Parsing failed due to invalid schema or format mismatch (`RuleParseError`).

### 4. Invariants
1. **Atomicity Boundary:** Output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) and `processed_ledger.json` are updated as an atomic unit. No partial or torn file writes are visible to external consumers.
2. **Queue Preservation on Failure:** The raw input file `data/raw/toSequence.txt` is cleared if and only if `run_batch()` completes successfully without raising an exception.
3. **Idempotency:** Any sequence already present in `processed_ledger.json` with a terminal outcome is skipped (`dedupe_hit=True`).
4. **Data Key Compatibility:** Outputs maintain backwards-compatible keys (`dna` and `dna_sequence`) across JSON and CSV formats.

### 5. Error Taxonomy
- `DNAProcessingError` (Base exception)
  - `RuleLoadError`: Raised when rule definitions cannot be loaded or parsed from `rules/`.
  - `PersistenceError`: Raised when writing temporary files or atomic renaming (`os.replace`) fails.

### 6. Idempotency Key Strategy
- **Key Formulation:** Raw `dna_sequence` string (e.g. `VOL08900750712`).
- **Ledger Persistence:** Stored in `data/processed_ledger.json` mapping `idempotency_key` to `{'terminal_outcome': outcome, 'timestamp': ISO_TIMESTAMP}`.

### 7. Telemetry & Required Logs
- **Batch Start:** `[BatchStart] correlation_id=<id> input_count=<count>`
- **Sequence Step:** `[Idempotency] key=<key> dedupe_hit=<bool> terminal_outcome=<outcome>`
- **Batch End:** `[BatchEnd] correlation_id=<id> processed_count=<count> ledger_total=<total>`

---

## Telemetry Grep Recipes
```bash
# View all batch execution starts and completions:
grep -E "\[BatchStart\]|\[BatchEnd\]" app.log

# Inspect idempotency deduplication hits:
grep "dedupe_hit=True" app.log

# Track processing failures:
grep "terminal_outcome=error" app.log
```
