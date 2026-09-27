# Chain Contract: DNA Batch Parsing

## Overview
The DNA Batch Parsing chain processes batch DNA sequences from `data/raw/toSequence.txt` and exports parsed representations to structured JSON and CSV outputs (`data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`), tracking processed records in `data/processed_ledger.json`.

## Contract Specification

- **Trigger**:
  - File presence/update in `data/raw/toSequence.txt` detected by watcher loop in `main.py`
  - Explicit execution via `python main.py --once` or direct `utils.dna_ui.main()` call

- **Inputs**:
  - `data/raw/toSequence.txt`: Newline-delimited text file containing raw DNA strings.
  - `rules/*.json`: Variable rulesets for parsing sound properties.

- **Terminal States**:
  - `SUCCESS`: All new DNA strings parsed or deduplicated; ledger updated; JSON and CSV files updated atomically; `toSequence.txt` cleared.
  - `ERROR`: Unhandled or persistence error raised (`RuleLoadError`, `DNAProcessingError`, `PersistenceError`); `toSequence.txt` retained without clearing.

- **Invariants**:
  - **Atomicity**: Output files (JSON, CSV) and ledger are written via temporary directory staging with explicit `flush` and `fsync` before `os.replace`. Partial/torn writes are impossible.
  - **Idempotency**: Processing a duplicate DNA sequence is a no-op that skips re-parsing and preserves previous ledger outcome.
  - **Consistency**: Input file `toSequence.txt` is cleared ONLY if batch execution completes without error.

- **Error Classes**:
  - `DNAProcessingError`: Base class for DNA processing exceptions.
  - `RuleLoadError`: Raised when JSON rule definitions cannot be read.
  - `PersistenceError`: Raised when writing temporary files or atomic replacement fails.

- **Idempotency Key**:
  - The raw DNA string (e.g. `VOL08900750712`).

- **Atomicity Boundary**:
  - All side-effects (JSON update, CSV update, ledger update) occur within a single atomic commit window using temp files in `data/output/`.

- **Required Logs**:
  - `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`

- **Grep Recipe Note**:
  - Search idempotency logs: `grep "\[Idempotency\]" <log_file>`
