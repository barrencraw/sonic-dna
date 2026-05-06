# Chain Contract: DNA Batch Parsing

## Trigger
- Manual invocation of `utils/dna_ui.py`
- Watcher in `main.py` detecting changes in `data/raw/toSequence.txt`
- CLI via `main.py --once`

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Idempotency ledger.

## Terminal States
- `SUCCESS`: All new DNA strings parsed and outputs committed.
- `ERROR`: Categorized failure (RuleLoadError, DNAProcessingError, PersistenceError).
- `SKIPPED`: All inputs already in ledger.

## Invariants
- `processed_ledger.json` matches the contents of `toSequence_parsed.json/csv`.
- No partial writes: if the process crashes, the previous valid outputs remain intact.
- `toSequence.txt` is only cleared by the caller (`main.py`) if the batch processor returns successfully.

## Error Classes
- `RuleLoadError`: Rules folder missing or malformed JSON.
- `RuleParseError`: Individual DNA string doesn't match any rule.
- `PersistenceError`: IO failure during atomic commit.

## Idempotency Key
- The raw DNA string.

## Atomicity Boundary
- The "Commit" phase where temp files are moved to `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json`.

## Required Logs
- `[Idempotency] key=<dna> dedupe_hit=<bool> terminal_outcome=<outcome>`
- `[OK] Processed <N> new DNA strings.`
- Telemetry markers for START and END.
