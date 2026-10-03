# Mini Chain Contract: DNA Batch Parsing Chain

## Overview
The DNA Batch Parsing Chain reads line-delimited DNA sequences from an input file, parses sound variable rules, appends results to cumulative dataset formats (JSON and CSV), and tracks processed sequences in a persistent ledger.

---

## Contract Specification

### 1. Trigger
- **Watcher loop** in `main.py` detecting non-empty content in `data/raw/toSequence.txt`.
- **CLI flag** `python main.py --once`.
- **Programmatic invocation** of `utils.dna_ui.run_batch()` (or `main()`).

### 2. Inputs
- `data/raw/toSequence.txt`: File containing line-delimited DNA sequences (e.g., `VOL08900750712`).
- Rule definitions loaded from `rules/rules_*.json`.

### 3. Terminal States
- **`SUCCESS`**: Batch processed completely; new sequences written to output datasets and ledger; input file truncated.
- **`SKIPPED`**: Sequences skipped because they were previously recorded in `processed_ledger.json`.
- **`ERROR`**: Exception raised during rule loading, sequence reading, or disk persistence. Input file `toSequence.txt` remains intact for retry.

### 4. Invariants
1. **Idempotency**: Sequences recorded in `processed_ledger.json` with a terminal outcome are never re-parsed or duplicate-appended to output files.
2. **Atomicity**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are written atomically via temp file write, `os.fsync`, and `os.replace`. Partial/torn writes are impossible.
3. **Queue Preservation**: `toSequence.txt` is cleared ONLY when `run_batch()` completes without unhandled errors.

### 5. Error Taxonomy
- `DNAProcessingError` (Base exception)
  - `RuleLoadError`: Failed to load or parse rules from `rules/` directory.
  - `PersistenceError`: I/O or atomic replacement failure during state/dataset serialization.
- `RuleParseError`: Malformed or invalid DNA sequence structure.

### 6. Idempotency Key
- Key: Stripped DNA sequence string (e.g. `VOL08900750712`).
- Persistence: `data/processed_ledger.json`.

### 7. Atomicity Boundary
- Writes occur inside `tempfile.TemporaryDirectory(dir=output_folder)`.
- Files flushed with `jf.flush()` and synced to disk using `os.fsync(jf.fileno())`.
- Renamed atomically using `os.replace(tmp_path, target_path)`.

### 8. Telemetry & Required Logs
- Start: `[Watcher] Started. Monitoring data/raw/toSequence.txt...`
- Step: `[Idempotency] key=<dna_string> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- End: `[OK] Processed <count> new DNA strings. Total in ledger: <total>`
- Error: `[Watcher][CRITICAL] DNA processing failed: <error>`

---

## Telemetry Grep Recipe

```bash
# Check deduplication hits and outcomes
grep "\[Idempotency\]" log.txt

# Monitor watcher execution and critical failures
grep -E "\[Watcher\]|\[CRITICAL\]" log.txt
```
