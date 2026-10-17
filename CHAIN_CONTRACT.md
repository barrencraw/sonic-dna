# Chain Contract: DNA Batch Parsing

## Overview
This contract governs the **DNA Batch Parsing** chain (`utils/dna_ui.py` triggered by `main.py` or standalone scripts). It defines the invariants, idempotency key strategy, atomicity boundaries, typed error taxonomy, and structured telemetry required for batch parsing operations.

---

## 1. Chain Specification

* **Trigger**: Invocation of `run_batch()` (or `main()`) in `utils/dna_ui.py`, triggered by `main.py` (Watcher loop / `--once` flag) or direct Python execution.
* **Inputs**:
  * `data/raw/toSequence.txt`: Newline-delimited list of DNA sequence strings.
  * `data/processed_ledger.json`: Persistent ledger mapping idempotency keys to terminal processing states.
  * `rules/*.json`: JSON rulesets defining variables, subvars, and encoding specifications.
* **Terminal States**:
  * `success`: DNA sequence parsed and appended to `toSequence_parsed.json` and `toSequence_parsed.csv`.
  * `error`: DNA sequence failed parsing (e.g. `RuleParseError`) and error details appended to output files.
  * `skipped`: DNA sequence already exists in `processed_ledger.json` with a terminal outcome (`success` or `error`).

---

## 2. Invariants & Boundaries

* **Idempotency Key**: The exact DNA string (e.g., `VOL08900750712`). Re-submitting an identical DNA string produces no duplicate entries in output files and does not re-trigger rule calculation.
* **Atomicity Boundary**:
  1. Parse input DNA sequences in memory.
  2. Write output files (`output.json` and `output.csv`) to a temporary staging directory in `data/output/`.
  3. Flush file buffers (`jf.flush()`) and sync to physical disk (`os.fsync()`).
  4. Perform atomic rename (`os.replace()`) to update `toSequence_parsed.json` and `toSequence_parsed.csv`.
  5. Update and persist `data/processed_ledger.json`.
  6. Main process/watcher truncates `data/raw/toSequence.txt` only after successful batch completion.
* **No Torn Writes**: If I/O or power failure occurs mid-write, the existing output files and ledger remain uncorrupted.

---

## 3. Error Taxonomy

* `DNAProcessingError`: Base exception for all batch parsing domain errors.
  * `RuleLoadError`: Raised when JSON rulesets cannot be loaded from `rules/`.
  * `PersistenceError`: Raised when writing temporary files or atomic renaming fails.
  * `RuleParseError`: Internal exception raised by `DNACalculator` when a sequence does not match rules.

---

## 4. Telemetry & Observability

All operational logs emitted during execution follow structured JSON formatting prefixed with `JSON_LOG:`.

### Mandatory Log Fields:
* `timestamp`: ISO 8601 UTC timestamp string.
* `correlation_id`: Execution trace identifier.
* `actor_id`: Component name executing the batch (`batch_parser` or `watcher`).
* `chain_name`: `"dna_batch_parsing"`.
* `step`: Step in the chain (`start`, `parse_sequence`, `skipped`, `persist`, `complete`).
* `outcome`: Key outcome status (`success`, `error`, `skipped`).
* `latency_ms`: Execution duration in milliseconds.
* `idempotency_key`: The DNA sequence identifier.
* `outcome_detail`: Detailed message or error string.

---

## 5. Telemetry Grep Recipes

* **Find all structured telemetry logs for DNA Batch Parsing**:
  ```bash
  grep "JSON_LOG:" | grep '"chain_name": "dna_batch_parsing"'
  ```
* **Find idempotency skip hits (deduplicated sequences)**:
  ```bash
  grep "JSON_LOG:" | grep '"step": "skipped"'
  ```
* **Find batch persistence failures**:
  ```bash
  grep "JSON_LOG:" | grep '"outcome": "error"'
  ```
