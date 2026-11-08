# Chain Contract: DNA Batch Parsing

## 1. Overview
The **DNA Batch Parsing** chain ingests raw DNA strings representing sound characteristics, parses them deterministically according to rule definitions, records outcomes in an idempotent ledger, and atomically commits cumulative JSON and CSV datasets.

## 2. Chain Specification
- **Trigger:**
  - File watcher monitoring `data/raw/toSequence.txt` for non-empty content changes.
  - Manual CLI invocation via `python main.py --once` or programmatic execution via `utils.dna_ui.run_batch()`.
- **Inputs:**
  - Input file: `data/raw/toSequence.txt` (newline-delimited DNA strings).
  - Rules folder: `rules/*.json` (e.g. `rules_Volume.json`, `rules_Timbre.json`).
  - Ledger file: `data/processed_ledger.json` (persisting processing history and terminal outcomes).
  - Existing outputs: `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`.
- **Terminal States:**
  - `success`: DNA sequence parsed successfully against rules and recorded in output.
  - `error`: DNA sequence failed parsing (e.g. `RuleParseError`), error recorded in output and ledger.
  - `skipped`: DNA sequence previously processed (ledger dedupe hit), not re-added to output.
- **Invariants:**
  1. **Idempotency:** Re-invoking the batch parser on identical DNA sequences produces zero duplicate entries in cumulative JSON and CSV outputs.
  2. **Atomicity:** Partial or torn writes never corrupt output files or the ledger. Output files are written to temporary files on the same filesystem and committed via atomic replace (`os.replace`).
  3. **Queue Draining Safety:** The input file (`toSequence.txt`) is cleared if and only if batch processing and persistence complete successfully.
  4. **No-op Cleanliness:** If all items are deduplicated (zero new items processed), output files are not touched.
- **Error Taxonomy:**
  - `DNAProcessingError` (base error)
  - `RuleLoadError` (raised when rule configurations cannot be loaded)
  - `PersistenceError` (raised when writing outputs or ledger fails)
  - `RuleParseError` (raised during parsing of invalid DNA strings; caught and recorded as terminal state `error`)
- **Idempotency Key:**
  - The DNA string itself (`dna_sequence`, e.g. `VOL08900750712`).
- **Atomicity Boundary:**
  - Temporary directory in `data/output/`: JSON and CSV outputs written and flushed (`fsync`) to disk before atomic rename (`os.replace`).
  - Ledger write flushed and saved when new items are processed.

## 3. Observability & Telemetry
Structured telemetry logs are emitted with the prefix `JSON_LOG:` formatted as JSON:
- `timestamp`: ISO 8601 UTC timestamp.
- `correlation_id`: Trace identifier for the batch run.
- `actor_id`: Actor triggering the chain (`batch_parser` or `watcher`).
- `chain_name`: `dna_batch_parsing`.
- `step`: `start`, `item_process`, `persist`, `end`.
- `outcome`: `started`, `success`, `error`, `skipped`, `completed`.
- `idempotency_key`: DNA string for item steps; `batch` for batch-level steps.
- `latency_ms`: Duration of the step or chain in milliseconds.

### Grep Recipes
- View all structured telemetry logs:
  ```bash
  grep "JSON_LOG:" app.log
  ```
- Filter by correlation ID:
  ```bash
  grep "JSON_LOG:" app.log | grep '"correlation_id": "<CID>"'
  ```
- Find all errors or failures:
  ```bash
  grep "JSON_LOG:" app.log | grep '"outcome": "error"'
  ```
- Check idempotency deduplication hits:
  ```bash
  grep "JSON_LOG:" app.log | grep '"step": "item_process"' | grep '"outcome": "skipped"'
  ```
