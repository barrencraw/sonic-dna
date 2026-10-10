# Chain Contract: DNA Batch Parsing

## 1. Overview & Trigger
- **Chain Name:** `dna_batch_parser`
- **Trigger:**
  - Manual invocation via CLI (`python main.py --once` or `run_batch()`)
  - Continuous file watcher detecting changes in `data/raw/toSequence.txt`
- **Actor ID:** Default `batch_parser` or caller trace string.

## 2. Inputs & Data Flow
- **Input File:** `data/raw/toSequence.txt` containing UTF-8 formatted DNA sequences (one per line).
- **Rule Files:** Rules loaded from `rules/*.json`.
- **Processed Ledger:** `data/processed_ledger.json` storing historical execution state and idempotency records.
- **Output Files:**
  - `data/output/toSequence_parsed.json`
  - `data/output/toSequence_parsed.csv`

## 3. Idempotency Strategy
- **Idempotency Key:** The trimmed DNA sequence string (e.g. `VOL08900750712`).
- **Deduplication Behavior:**
  - Before parsing, check if `idempotency_key` exists in `data/processed_ledger.json`.
  - If found in ledger, mark as `dedupe_hit=True`, log deduplication step, and skip calculation.
  - If not found, process sequence, record terminal outcome (`success` or `error: <reason>`), and persist to ledger.

## 4. Terminal States
- `success`: Sequence successfully parsed against loaded JSON rules.
- `error`: Sequence parsing failed due to invalid prefix, missing rule, or malformed value.
- `skipped`: Sequence skipped due to prior idempotency hit in ledger.

## 5. Invariants
1. **At-Most-Once State Mutation per Key:** Processing a key twice will not duplicate output entries or ledger records.
2. **Atomicity Boundary:** Either both output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) and `processed_ledger.json` are atomically updated together, or none are updated.
3. **Queue Retention on Failure:** If processing or output persistence fails with an unhandled exception, `data/raw/toSequence.txt` must not be cleared, allowing retry.
4. **Schema Coherence:** Outputs must retain backward compatibility with both `dna` and `dna_sequence` key mappings.

## 6. Error Taxonomy
- `DNAProcessingError` (Base Exception)
  - `InputReadError`: Raised when reading `data/raw/toSequence.txt` fails.
  - `RuleLoadError`: Raised when initializing `DNACalculator` rules fails.
  - `PersistenceError`:
    - `LedgerLoadError`: Raised when reading/parsing `processed_ledger.json` fails due to corruption.
    - `LedgerSaveError`: Raised when writing updated ledger fails.
    - `AtomicWriteError`: Raised when temporary file sync or atomic rename (`os.replace`) fails.

## 7. Required Structured Logs
All step transitions emit structured JSON logs prefixed with `JSON_LOG:`:
- Fields: `timestamp` (UTC ISO 8601), `correlation_id`, `actor_id`, `chain_name`, `step`, `outcome`, `latency_ms`, `idempotency_key`, `outcome_detail`.
- Steps: `start`, `read_input`, `dedupe_check`, `parse_sequence`, `atomic_write`, `end`.

## 8. Grep Recipes for Telemetry Inspection
```bash
# Extract all structured JSON logs from process output
grep "JSON_LOG:" app.log | sed 's/JSON_LOG: //' | jq .

# Filter logs by correlation ID
grep "JSON_LOG:" app.log | grep "<correlation_id>"

# Count deduplication hits
grep "JSON_LOG:" app.log | grep '"step":"dedupe_check"' | grep '"outcome":"skipped"'
```
