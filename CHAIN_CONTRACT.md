# Chain Contract: DNA Batch Parsing

## 1. Overview & Goal
The **DNA Batch Parsing** chain is responsible for reading raw DNA sequences from `data/raw/toSequence.txt`, validating/parsing them against modular rules defined in `rules/*.json`, updating the processed ledger (`data/processed_ledger.json`), and writing cumulative output files (`data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`).

## 2. Trigger
- **Watcher thread (`main.py`)**: Continuously monitors `data/raw/toSequence.txt` for new sequences.
- **CLI One-Run (`main.py --once`)**: Processes current input sequences once and exits.
- **Programmatic API (`utils.dna_ui.run_batch`)**: Called with optional trace context (`correlation_id`, `actor_id`).

## 3. Inputs
- `input_path`: Path to `data/raw/toSequence.txt` (default) containing raw DNA sequences, one per line.
- `correlation_id`: Trace UUID string for request tracking.
- `actor_id`: Identifier of the invoking actor (default: `'batch_parser'`).

## 4. Terminal States
Each DNA sequence processed resolves to one of four terminal statuses (`DNAStatus` enum):
- `success`: Successfully parsed by matching rule in `rules/*.json`.
- `error`: Failed parsing (e.g., `RuleParseError` or invalid format).
- `skipped`: Deduplicated because sequence already exists in processed ledger.
- `refused`: Processing rejected (e.g., due to system thermal lockout / `ThermalOverloadError`).

## 5. Invariants
- **Atomicity**: Either both JSON and CSV output files are fully written and committed, or neither is modified. Output files are rewritten only if `new_processed_count > 0`.
- **Idempotency**: Retrying the same DNA sequence will never produce duplicate records in output JSON/CSV or accumulate duplicate heat.
- **Thermal Fatigue Boundary**:
  - Each parsed DNA sequence (whether `success` or `error`) adds **2.0 heat units** to `core_heat`.
  - System cools down at a rate of **0.5 heat units per second** elapsed since `last_processed_timestamp`.
  - Safety lockout threshold is **10.0 heat units**. If heat threshold is reached/exceeded, processing stops and raises `ThermalOverloadError`.
- **No Silent Drains**: If processing fails or is refused due to `ThermalOverloadError`, `main.py` catches the error and preserves `data/raw/toSequence.txt` so no sequences are silently dropped.
- **Backward Compatibility**: JSON and CSV output entries contain both legacy `dna` and canonical `dna_sequence` keys.

## 6. Error Taxonomy
Inheritance hierarchy rooted at `DNAProcessingError`:
- `DNAProcessingError`: Base class for all batch parsing exceptions.
  - `RuleLoadError`: Rules folder missing or unparseable.
  - `InputReadError`: Failure reading raw input file.
  - `ThermalOverloadError`: Raised when core heat exceeds safety lockout threshold.
  - `PersistenceError`: Base class for storage/I/O failures.
    - `LedgerLoadError`: Ledger JSON exists but is corrupted.
    - `LedgerSaveError`: Failed to write ledger JSON.
    - `AtomicWriteError`: Temp file creation, flush/fsync, or rename failed.

## 7. Idempotency Key Strategy
- **Key**: Raw stripped DNA sequence (e.g., `"VOL08900750712"`).
- **Lookup**: Checked against `data/processed_ledger.json`. Any key with a terminal outcome (`success`, `error`, `skipped`, `refused`, or legacy `SUCCESS`/`ERROR`) is skipped.

## 8. Atomicity Boundary
1. Generate temporary files in a subfolder inside `data/output/`.
2. Write JSON and CSV outputs to temporary files.
3. Call `jf.flush()` and `os.fsync(jf.fileno())` on temporary handles to guarantee physical persistence.
4. Execute `os.replace()` to atomically swap temporary files into destination paths.

## 9. Telemetry & Required Logs
Structured JSON telemetry lines are logged with prefix `JSON_LOG:` and contain the following mandatory schema fields:
- `timestamp`: UTC ISO 8601 string (e.g., `2025-06-02T12:00:00Z`).
- `correlation_id`: Trace UUID string.
- `actor_id`: Calling actor (`batch_parser`).
- `chain_name`: `"dna_batch_parsing"`.
- `step`: Process step (`"start"`, `"read_input"`, `"dedupe_check"`, `"parse_sequence"`, `"atomic_write"`, `"save_ledger"`, `"end"`).
- `outcome`: Outcome status string (`"success"`, `"error"`, `"skipped"`, `"refused"`).
- `latency_ms`: Execution duration in milliseconds.
- `idempotency_key`: DNA sequence string or `null`.
- `outcome_detail`: Descriptive detail or error message.

## 10. Grep Recipes
- View all structured telemetry logs:
  `grep "JSON_LOG:" app.log`
- View thermal overload events:
  `grep -i "thermal_lockout\|ThermalOverloadError" app.log`
- View idempotency deduplication hits:
  `grep "dedupe_hit=True" app.log`
- View atomic write operations:
  `grep "atomic_write" app.log`
