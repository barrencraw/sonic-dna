# Chain Contract: DNA Batch Parsing Chain

## Trigger
- **Watcher process (`main.py`)**: Automatic background monitoring of `data/raw/toSequence.txt`.
- **CLI One-Runner (`main.py --once`)**: Manual or script-driven one-time execution.
- **Direct invocation (`utils/dna_ui.py:run_batch()`)**: Direct program call.

## Inputs
- `data/raw/toSequence.txt`: Text file containing raw DNA strings (one sequence per line).
- `rules/*.json`: Declarative JSON rule definition files defining the syntax and subvariables for DNA parsing.

## Terminal States
1. **SUCCESS**: All new DNA sequences in `toSequence.txt` are parsed, saved to `toSequence_parsed.json`, `toSequence_parsed.csv`, recorded in `data/processed_ledger.json`, and input file `toSequence.txt` cleared.
2. **SKIPPED (Deduplicated)**: Sequence already recorded in `processed_ledger.json` is skipped without re-parsing or duplicating entries in output files.
3. **PARTIAL / HANDLED ERROR**: Unparseable DNA sequences generate error entries in output files and terminal outcome `error: <reason>` in `processed_ledger.json`.
4. **FATAL FAILURE**: I/O or persistence failures raise explicit `PersistenceError` / `AtomicWriteError`, retaining `toSequence.txt` for retry without file corruption.

## Invariants
1. **Atomicity**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`) are updated atomically via temp file writes + `os.replace`. Partial or torn writes never occur on disk.
2. **Idempotency**: Processing the same DNA sequence multiple times produces identical state without duplicate output records.
3. **Input Retention on Infrastructure Error**: If batch processing fails due to `PersistenceError` or unhandled infrastructure exceptions, `toSequence.txt` is NOT cleared by `main.py`.

## Error Taxonomy
- `DNAProcessingError(Exception)`: Base exception for all DNA processing errors.
  - `RuleLoadError(DNAProcessingError)`: Raised when loading rule JSON files from `rules/` fails.
  - `InputReadError(DNAProcessingError)`: Raised when reading `data/raw/toSequence.txt` fails.
  - `PersistenceError(DNAProcessingError)`: Base class for persistence/storage failures.
    - `LedgerLoadError(PersistenceError)`: Raised when loading `processed_ledger.json` fails.
    - `LedgerSaveError(PersistenceError)`: Raised when saving `processed_ledger.json` fails.
    - `AtomicWriteError(PersistenceError)`: Raised when temporary file creation, write, fsync, or rename fails during commit.

## Idempotency Key Strategy
- **Key**: The raw DNA string (e.g., `VOL08900750712`).
- **Storage**: `data/processed_ledger.json` mapping `key -> {'terminal_outcome': string, 'timestamp': string}`.
- **Deduplication Check**: Before parsing, check if `key in ledger`. If true, skip re-computation and output generation.

## Atomicity Boundary
- All output files (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`) are written into a single temporary directory under `data/output/`.
- File handles are explicitly flushed (`jf.flush()`) and synced to disk (`os.fsync(jf.fileno())`).
- Renames (`os.replace`) commit all files atomically to final paths.

## Required Logs
- Start: `[Watcher] Started. Monitoring data/raw/toSequence.txt...` or `[Once-Runner] Processing all DNA strings once...`
- Idempotency Dedupe Hit: `[Idempotency] key=<KEY> dedupe_hit=True terminal_outcome=<OUTCOME>`
- Idempotency Dedupe Miss: `[Idempotency] key=<KEY> dedupe_hit=False terminal_outcome=<OUTCOME>`
- Success Summary: `[OK] Processed <N> new DNA strings. Total in ledger: <TOTAL>`
- Errors: `[Watcher][CRITICAL] DNA processing failed: <ERROR>`

## Grep Recipes
- Check Idempotency hits:
  `grep "\[Idempotency\].*dedupe_hit=True" logs/app.log`
- Find processing failures:
  `grep "\[CRITICAL\]" logs/app.log`
- Track batch runs:
  `grep "\[OK\] Processed" logs/app.log`
