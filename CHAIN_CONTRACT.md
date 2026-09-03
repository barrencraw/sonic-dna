# Chain Contract: DNA Batch Parsing Chain

## Overview
This contract defines the execution semantics, atomicity boundaries, idempotency key strategy, invariants, error taxonomy, and observability for the DNA Batch Parsing pipeline in SonicDNA (`main.py` / `utils/dna_ui.py`).

---

## Contract Specification

### 1. Trigger
- Execution via `main.py --once` (`process_once()`) or `run_batch()`.
- Automated execution via the `watch_loop()` in `main.py` when new non-empty sequences are written to `data/raw/toSequence.txt`.

### 2. Inputs
- `data/raw/toSequence.txt`: Text file containing newline-delimited raw DNA sequence strings.
- `rules/*.json`: Variable rule definitions specifying parsing schemas and valid value ranges.
- `data/processed_ledger.json`: Historical key-value store tracking processed DNA sequences and terminal outcomes.
- `data/output/toSequence_parsed.json`: Cumulative JSON dataset.
- `data/output/toSequence_parsed.csv`: Cumulative CSV dataset.

### 3. Terminal States
- `success`: DNA sequence successfully parsed according to rule specifications; results staged and committed to output stores and ledger.
- `error: <reason>`: DNA sequence failed rule parsing; recorded as an error entry in output stores and ledger.
- `skipped`: DNA sequence key already exists in `processed_ledger.json`; bypassed without duplicated I/O or computation.

### 4. Invariants
- **Deduplication**: Every processed DNA sequence string serves as its own idempotency key. Repeating sequences present in `processed_ledger.json` result in `dedupe_hit=True` and do not produce duplicate entries in `toSequence_parsed.json` or `toSequence_parsed.csv`.
- **Atomicity**: Updates to output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are committed atomically. Partial writes, half-written files, or inconsistent outputs are forbidden.
- **Input Preservation on Failure**: `data/raw/toSequence.txt` is cleared by the watcher only after `run_batch()` completes successfully without raising errors. On exception, `toSequence.txt` remains intact for retry.

### 5. Error Taxonomy
- `DNAProcessingError`: Root exception for DNA processing failures.
- `RuleLoadError` (`DNAProcessingError`): Raised when rule definitions in `rules/` cannot be read or initialized.
- `PersistenceError` (`DNAProcessingError`): Raised when temporary file creation, flushing/syncing, or atomic rename (`os.replace`) fails during persistence.

### 6. Idempotency Key Strategy
- **Key Definition**: `idempotency_key = dna_sequence.strip()`
- **Ledger Storage**:
```json
{
  "<dna_sequence>": {
    "terminal_outcome": "success" | "error: <reason>",
    "timestamp": "YYYY-MM-DD HH:MM:SS"
  }
}
```

### 7. Atomicity Boundary
- All modified outputs (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`) are written inside a temporary directory created in `data/output/` (on the same filesystem).
- File handles call `.flush()` and `os.fsync(fd)` to guarantee physical disk write before committing.
- Commit phase uses `os.replace(tmp_path, target_path)` for atomic filesystem transition.

### 8. Telemetry & Observability
- `[BatchStart] total_sequences=<N>`
- `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `[BatchEnd] new_processed=<N> total_in_ledger=<M>`

### 9. Grep Recipe
To inspect execution logs for batch triggers and idempotency hits:
```bash
grep -E "\[(BatchStart|Idempotency|BatchEnd)\]" <log_file>
```
