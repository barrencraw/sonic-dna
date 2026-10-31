# Chain Contract: DNA Batch Parsing

## 1. Overview & Trigger
- **Chain Name:** `dna_batch_parser`
- **Trigger:**
  - Watcher loop in `main.py` when non-empty content is appended to `data/raw/toSequence.txt`.
  - Manual CLI execution via `main.py --once`.
  - Programmatic invocation via `utils.dna_ui.run_batch(correlation_id=None)`.

## 2. Inputs & Context
- **Primary Input File:** `data/raw/toSequence.txt` containing one raw DNA sequence per line.
- **Rules Directory:** `rules/rules_*.json` containing JSON rule schemas for decoding DNA prefixes and fields.
- **Cumulative Ledger:** `data/processed_ledger.json` tracking processed sequences and outcomes.
- **Context:**
  - `correlation_id` (str, UUIDv4): Carried across batch execution.
  - `actor_id` (str): Identifier of the caller (e.g., `batch_parser`, `watcher`).

## 3. Terminal States & Outcomes
- `success`: DNA sequence parsed and written to output files and ledger.
- `error`: DNA sequence failed schema parsing (`RuleParseError`); error recorded in output and ledger.
- `skipped`: DNA sequence already exists in the ledger; skipped to preserve idempotency.

## 4. Invariants
- **Atomicity:** All outputs (`data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`, and `data/processed_ledger.json`) are updated together atomically via staging in a temporary folder and `os.replace`. Either all outputs are updated or none are.
- **Zero-Mutation on Deduplication:** If all inputs are duplicate hits (0 new sequences), output files are not touched and no atomic writes occur.
- **Watcher Safety:** Input file `data/raw/toSequence.txt` is only truncated/cleared if batch processing succeeds without raising an unhandled exception.
- **Determinism:** Identical input sequences and rules produce identical structured parse dictionaries and CSV rows.

## 5. Error Taxonomy
- `DNAProcessingError`: Base class for all batch processing errors.
  - `RuleLoadError`: Raised when rule definitions in `rules/` fail to load or are invalid.
  - `PersistenceError`: Raised when writing, staging, syncing, or replacing ledger and output files fails.

## 6. Idempotency Strategy
- **Idempotency Key:** The stripped DNA sequence string itself (e.g., `VOL08900750712`).
- **Storage:** Persisted in `data/processed_ledger.json`.
- **Deduplication Check:** If `idempotency_key` is present in `ledger`, the entry is skipped, logging `outcome="skipped"` and `dedupe_hit=True`.

## 7. Atomicity Boundary
1. Collect all newly parsed results in memory.
2. If `new_processed_count > 0`:
   - Create a temporary staging directory in the same filesystem as target directories (`data/output` / `data`).
   - Write updated JSON, CSV, and ledger files into temporary files.
   - Flush and `os.fsync` each temporary file descriptor.
   - Atomically replace target files via `os.replace`.

## 8. Required Logs & Grep Recipes
All lifecycle events are logged as structured JSON with prefix `JSON_LOG: ` containing:
- `timestamp`: UTC ISO-8601 string (`YYYY-MM-DDTHH:MM:SSZ`)
- `correlation_id`: Context trace UUID
- `actor_id`: Actor executing the chain
- `chain_name`: `dna_batch_parser`
- `step`: `start`, `parse_sequence`, `commit`, `end`
- `outcome`: `processing`, `success`, `error`, `skipped`, `failed`
- `latency_ms`: Float elapsed milliseconds
- `idempotency_key`: DNA sequence string (or `None` for batch-level logs)

### Grep Recipes:
- View all batch lifecycle events:
  ```bash
  grep "JSON_LOG:" app.log
  ```
- Filter for failures:
  ```bash
  grep "JSON_LOG:" app.log | grep -E '"outcome":\s*"(error|failed)"'
  ```
- Trace a specific transaction by correlation ID:
  ```bash
  grep "JSON_LOG:" app.log | grep "<correlation_id>"
  ```
