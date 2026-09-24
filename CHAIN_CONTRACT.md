# Chain Contract: DNA Batch Parsing Chain

## Overview
This contract defines the operational boundaries, invariants, and failure modes for the **DNA Batch Parsing Chain** (`main.py` watcher / `--once` runner and `utils/dna_ui.py`).

---

## Contract Specification

### 1. Trigger
- Periodic polling or manual invocation via `main.py` (watcher thread or `--once` flag) when non-empty content exists in `data/raw/toSequence.txt`.

### 2. Inputs
- `data/raw/toSequence.txt`: Text file containing newline-separated raw DNA sequences.
- `rules/*.json`: Rule definition files specifying variable decoding schemes.
- `data/processed_ledger.json`: Ledger tracking previously processed DNA sequences and terminal outcomes.

### 3. Terminal States
- **SUCCESS**: All new DNA sequences in `toSequence.txt` were successfully parsed and appended to JSON/CSV stores and recorded in `processed_ledger.json`. `toSequence.txt` is cleared.
- **NO_OP**: `toSequence.txt` contains no new DNA sequences (all sequences present were deduplicated via `processed_ledger.json`). `toSequence.txt` is cleared.
- **FAILURE (HANDLED)**: Individual sequence failed rule parsing (`RuleParseError`). Failure is recorded as terminal state `error` in ledger and JSON/CSV outputs. Processing continues for remaining sequences. `toSequence.txt` is cleared.
- **FAILURE (UNHANDLED / SYSTEM)**: System exception occurred (e.g. `PersistenceError`, `RuleLoadError`, `DNAProcessingError`). Transaction aborted. Outputs and ledger are uncommitted; `toSequence.txt` is **NOT** cleared to enable retries.

### 4. Invariants
- **Atomicity**: Updates to `data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`, and `data/processed_ledger.json` occur all-or-nothing via temporary file directory writes and atomic file renames (`os.replace`).
- **Idempotency**: DNA sequences present in `processed_ledger.json` are skipped (`dedupe_hit=True`), preventing duplicate side-effects in cumulative JSON and CSV outputs.
- **Input Retention on Failure**: `data/raw/toSequence.txt` is truncated/cleared **only** after batch execution succeeds without throwing persistent errors.

### 5. Error Taxonomy
- `DNAProcessingError`: Base exception for all DNA processing errors.
- `RuleLoadError` (`DNAProcessingError`): Raised when rule definition files cannot be loaded.
- `PersistenceError` (`DNAProcessingError`): Raised when atomic persistence or ledger updates fail.
- `RuleParseError`: Raised when an individual DNA string fails rule format decoding.

### 6. Idempotency Key Strategy
- **Key Formulation**: Raw DNA sequence string (e.g., `VOL08900750712`).
- **Ledger Record**: `data/processed_ledger.json` maps `key -> { terminal_outcome, timestamp }`.

### 7. Required Logs & Telemetry
- **Deduplication Check**: `[Idempotency] key=<DNA_KEY> dedupe_hit=<True|False> terminal_outcome=<OUTCOME>`
- **Batch Result**: `[OK] Processed <N> new DNA strings. Total in ledger: <TOTAL>`
- **Critical Failure**: `[<TIMESTAMP>][Watcher][CRITICAL] DNA processing failed: <ERROR>`

### 8. Grep Recipes
- Check deduplication hits:
  ```bash
  grep "dedupe_hit=True" logs.txt
  ```
- Monitor batch parser errors:
  ```bash
  grep -E "\[CRITICAL\]|\[ERROR\]" logs.txt
  ```
