# Chain Contract: DNA Batch Parsing

## Trigger
- File modification event detected by watcher thread in `main.py` on `data/raw/toSequence.txt`.
- Manual/CLI execution via `python main.py --once` or direct invocation of `run_batch()` in `utils/dna_ui.py`.

## Inputs
- `data/raw/toSequence.txt`: Plain text file containing line-delimited DNA sequence strings.
- `rules/rules_*.json`: JSON specification files for SonicDNA rule matching and calculation.
- `data/processed_ledger.json`: Persistence ledger tracking processed idempotency keys and terminal states.

## Terminal States
- `SUCCESS`: DNA sequence successfully parsed according to matching rule; outputs appended to JSON and CSV formats, and key recorded in ledger with `terminal_outcome: success`.
- `ERROR`: DNA sequence parsing failed (e.g., `RuleParseError`); error entry appended to JSON and CSV formats, and key recorded in ledger with `terminal_outcome: error: <message>`.
- `SKIPPED`: DNA sequence already present in `processed_ledger.json` with a terminal outcome; processing skipped to ensure idempotency.

## Invariants
1. **Idempotency:** Re-processing an identical DNA sequence must not produce duplicate entries in `toSequence_parsed.json` or `toSequence_parsed.csv`.
2. **Atomicity:** Partial or failed writes must never leave corrupt or truncated output files on disk (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`).
3. **Watcher Safety:** Input file (`toSequence.txt`) is truncated/cleared if and only if `run_batch()` completes without raising a `DNAProcessingError` or `PersistenceError`.

## Error Classes
- `DNAProcessingError`: Base exception class for DNA parsing execution errors.
- `RuleLoadError` (subclass of `DNAProcessingError`): Raised when rules directory or rule files cannot be loaded.
- `PersistenceError` (subclass of `DNAProcessingError`): Raised when atomic file writing or replacement fails.

## Idempotency Key
- The raw DNA sequence string (`dna_str`), normalized by stripping leading and trailing whitespace.

## Atomicity Boundary
- File outputs (`toSequence_parsed.json` and `toSequence_parsed.csv`) are written to a temporary directory inside `data/output/`, flushed (`jf.flush()`), synced to disk (`os.fsync()`), and atomically renamed via `os.replace()` to their destination paths.
- `processed_ledger.json` is updated and saved atomically following successful batch processing.

## Required Telemetry Logs
Structured JSON logs formatted with prefix `JSON_LOG:` and including fields:
- `timestamp`: UTC ISO 8601 string (`YYYY-MM-DDTHH:MM:SSZ`).
- `correlation_id`: Trace UUID string.
- `actor_id`: Initiator identifier (`batch_parser` or caller name).
- `chain_name`: `dna_batch_parse`.
- `step`: `start`, `parse_sequence`, `commit_output`, or `end`.
- `outcome`: `SUCCESS`, `ERROR`, or `SKIPPED`.
- `latency_ms`: Execution latency in milliseconds.
- `idempotency_key`: DNA sequence string (or `batch` for process-level logs).
- `outcome_detail`: Succinct status message or error detail.

## Grep Recipes
```bash
# Filter all structured JSON logs for DNA batch parsing
grep "JSON_LOG:" app.log

# Search for idempotency deduplication events
grep "JSON_LOG:" app.log | grep '"outcome":"SKIPPED"'

# Extract errors during DNA batch execution
grep "JSON_LOG:" app.log | grep '"outcome":"ERROR"'
```
