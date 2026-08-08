# Chain Contract: DNA Batch Parsing

This contract specifies the execution rules, invariants, and boundaries for the DNA Batch Parsing chain in SonicDNA.

## 1. Chain Identification
* **Chain Name**: `dna_batch_parsing`
* **Trigger**:
  * Background File Watcher (`main.py`) detecting non-empty changes in `data/raw/toSequence.txt`.
  * One-time batch runner execution via `python3 main.py --once`.

## 2. Inputs & Outputs
* **Inputs**:
  * Raw DNA file: `data/raw/toSequence.txt` containing newline-separated DNA strings (e.g., `VOL08900750712`).
  * Rulesets: All defined JSON rulesets in the `rules/` directory (e.g., `rules_Volume.json`).
* **Outputs / Cumulative Stores**:
  * Cumulative JSON: `data/output/toSequence_parsed.json`
  * Cumulative CSV: `data/output/toSequence_parsed.csv`
  * Transaction Ledger: `data/processed_ledger.json`

## 3. Idempotency & Deduplication
* **Idempotency Key**: The DNA string itself (e.g., `VOL08900750712`).
* **Deduplication Logic**:
  * Every DNA string is checked against the cumulative ledger.
  * If a DNA string has been processed previously, its processing is skipped. This prevents redundant CPU/IO execution and duplicates in cumulative outputs.
* **Outcome Mapping**:
  * Skips logging of known items while emitting `dedupe_hit=True`.

## 4. Atomicity & Hard Boundaries
* **Atomicity Boundary**: Writes to cumulative stores and the ledger must be completely atomic.
* **Implementation Mechanism**:
  * Files are written to a temporary file (or temporary directory) on the same storage partition.
  * Output handles are explicitly flushed (`flush()`) and committed to disk (`os.fsync()`).
  * Temporary files replace the actual target files using `os.replace()`, which guarantees atomic commit.
* **Invariants**:
  * `toSequence.txt` is cleared **only if** `run_batch()` finishes successfully (all parsed and safely written).
  * No partial/torn writes or corrupted JSON/CSV/Ledger states can persist on disk under crash scenarios.

## 5. Exception Taxonomy
* `DNAProcessingError` (Base class)
  * `RuleLoadError`: Triggered if system rules cannot be loaded.
  * `PersistenceError`: Triggered if writing outputs atomically fails.
    * `LedgerSaveError`: Triggered if atomic saving of the processed ledger fails.
  * `RuleParseError` (raised by `DNACalculator`): Triggered when an individual DNA string violates rules. Caught per item, recorded as an `error` outcome, and does not halt the entire batch.

## 6. Required Log Telemetry
Every batch execution emits standardized JSON telemetry lines starting with the prefix `JSON_LOG:`.
* **Mandatory Fields**:
  * `timestamp` (ISO 8601 in UTC with `Z` suffix, millisecond precision)
  * `correlation_id` (UUID or unique string tracking transaction context)
  * `actor_id` (the executor, defaults to `"system"`)
  * `chain_name` (always `"dna_batch_parsing"`)
  * `step` (describing current execution phase, e.g., `batch_start`, `dedupe_check`, `process_item`, `save_outputs`, `batch_end`)
  * `outcome` (`success`, `skipped`, or `error`)
  * `latency_ms` (time elapsed in milliseconds)
  * `idempotency_key` (the DNA sequence or `"N/A"`)
  * `outcome_detail` (concise human-readable details)
