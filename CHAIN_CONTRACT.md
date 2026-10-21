# Chain Contract: DNA Batch Parsing

## Metadata
- **Chain Name:** DNA Batch Parsing
- **Primary Modules:** `utils/dna_ui.py`, `main.py`

## Trigger & Inputs
- **Trigger:** Watcher polling loop in `main.py`, single batch command (`python main.py --once`), or direct module invocation `run_batch()`.
- **Inputs:** `data/raw/toSequence.txt` (text file with raw DNA string per line).

## Terminal States
1. `success`: DNA string successfully parsed and results added to ledger and output datasets.
2. `error: <details>`: DNA string failed parsing (e.g. `RuleParseError`), error recorded in ledger and output datasets.
3. `skipped`: DNA string already exists in `processed_ledger.json`, duplicate execution skipped.

## Invariants
1. **Deduplication:** Repeated DNA strings are matched against `processed_ledger.json` and processed at-most-once.
2. **Atomicity:** File writes to `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv` are atomic using temp files, `fsync()`, and `os.replace()`. No torn or partial writes are visible on crash.
3. **Queue Preservation on Failure:** `main.py` only clears `toSequence.txt` if `run_batch()` succeeds without unhandled exceptions.

## Error Taxonomy
- `DNAProcessingError`: Base class for DNA processing exceptions.
- `RuleLoadError`: Raised when rule JSON definitions cannot be loaded from `rules/`.
- `PersistenceError`: Raised when writing temporary files or atomically replacing output files fails.

## Idempotency Key
- `dna_string`: The stripped raw string value from `toSequence.txt` (e.g., `VOL08900750712`).

## Atomicity Boundary
- Directory scope: `data/output/`
- Pattern:
  1. Write outputs inside temporary directory (`tempfile.TemporaryDirectory(dir=output_folder)`).
  2. Flush and sync file descriptors (`jf.flush()`, `os.fsync(jf.fileno())`).
  3. Perform atomic file replacement (`os.replace(tmp_file, output_path)`).

## Telemetry & Logging Standard
- `[Batch Parser] Start input={input_path}`
- `[Idempotency] key={idempotency_key} dedupe_hit={True|False} terminal_outcome={outcome}`
- `[Batch Parser] Completed processed={new_count} total_ledger={total_count}`

### Grep Recipe
```bash
grep -E "\[Batch Parser\]|\[Idempotency\]" logs.txt
```
