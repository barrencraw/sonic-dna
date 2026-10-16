# Chain Contract: DNA Batch Parsing (`dna_batch_parser`)

## 1. Trigger & Scope
- **Trigger**: File update in `data/raw/toSequence.txt` detected by Watcher loop (`main.py`) or manual single run invocation (`python main.py --once` / `run_batch()`).
- **Chain Name**: `dna_batch_parser`
- **Actor ID**: `batch_parser`

## 2. Inputs & Dependencies
- **Primary Input**: `data/raw/toSequence.txt` (plain text, newline-separated DNA sequences).
- **Rule Definitions**: `rules/*.json` loaded via `utils/dna_calculator.DNACalculator`.
- **Ledger State**: `data/processed_ledger.json` (maps idempotency key to terminal outcome and timestamp).

## 3. Terminal States
- **`SUCCESS`**: All new (non-deduplicated) DNA sequences processed successfully; cumulative JSON and CSV outputs persisted atomically; ledger updated; raw input cleared by caller.
- **`SKIPPED`**: Input file empty or all DNA sequences deduplicated against ledger; no file persistence required.
- **`FAILED`**: Failure during rule load (`RuleLoadError`), input reading (`DNAProcessingError`), or atomic output persistence (`PersistenceError`). Input file retained for retry.

## 4. System Invariants
1. **Atomic File Persistence (No Torn Writes)**: JSON and CSV files are written to a temporary folder on the same filesystem, flushed, fsynced, and atomically replaced (`os.replace`).
2. **Strict Idempotency**: Sequences recorded in `processed_ledger.json` are skipped on subsequent invocations without duplicate side-effects.
3. **Input File Preservation on Failure**: `toSequence.txt` is only truncated when `run_batch()` returns without raising an exception.

## 5. Error Taxonomy
- `DNAProcessingError` (Base Class): Generic batch execution failure.
  - `RuleLoadError` (Subclass): Incapable of reading or parsing rule specifications from `rules/`.
  - `PersistenceError` (Subclass): Failure during temporary file generation, syncing, or atomic replacement.

## 6. Idempotency Strategy
- **Idempotency Key**: Raw DNA sequence string (e.g., `VOL08900750712`).
- **Storage**: Key-value store in `data/processed_ledger.json`.
- **Deduplication Check**:
  ```python
  if idempotency_key in ledger:
      # Skip processing and record dedupe_hit=True
  ```

## 7. Atomicity Boundary
The atomicity boundary encapsulates file writes and ledger updates:
1. Write JSON and CSV into `tempfile.TemporaryDirectory(dir=output_folder)`.
2. Execute `jf.flush()` and `os.fsync(jf.fileno())`.
3. Atomic replacement via `os.replace(tmp_file, output_file)`.
4. Persist updated `data/processed_ledger.json`.

## 8. Required Telemetry & Observability Logs
All telemetry events are emitted as JSON strings prefixed with `JSON_LOG:`.
Standard schema fields:
- `timestamp`: UTC ISO 8601 formatted timestamp (`%Y-%m-%dT%H:%M:%SZ`).
- `correlation_id`: Unique trace UUID for the invocation batch.
- `actor_id`: `batch_parser`.
- `chain_name`: `dna_batch_parser`.
- `step`: `start` | `dedupe` | `parse_sequence` | `persist_outputs` | `end`.
- `outcome`: `success` | `skipped` | `error`.
- `latency_ms`: Duration in milliseconds for step or total run.
- `idempotency_key`: Optional DNA sequence string when processing specific sequence.
- `outcome_detail`: Contextual error message or result summary.

## 9. Telemetry Grep Recipes
- **Extract all structured telemetry logs**:
  ```bash
  grep 'JSON_LOG:' execution.log
  ```
- **Trace a specific correlation flow**:
  ```bash
  grep 'JSON_LOG:' execution.log | grep '<correlation_id>'
  ```
- **Find all deduplication hits**:
  ```bash
  grep '"step": "dedupe"' execution.log
  ```
- **Inspect failures and errors**:
  ```bash
  grep '"outcome": "error"' execution.log
  ```
