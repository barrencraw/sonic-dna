# Chain Contract: DNA Batch Parsing

## Description
Processes a list of DNA sequences from a text file, parsing them according to modular rules and persisting the results in JSON, CSV, and an idempotency ledger.

## Trigger
- `main.py --once`: Manual single-run execution.
- `main.py` (Watcher): Automatically triggered when `data/raw/toSequence.txt` is modified.

## Inputs
- `data/raw/toSequence.txt`: A plain text file with one DNA sequence per line.
- `rules/*.json`: Modular rule definitions for parsing.

## Terminal States
- `SUCCESS`: All new sequences parsed and persisted atomically.
- `DEDUPE_SKIP`: Sequence already exists in `ledger.json` and was skipped.
- `PARSE_ERROR`: Sequence format invalid; recorded as error in output and ledger.
- `ATOMIC_FAILURE`: Persistence failed; no changes made to output files or ledger.

## Invariants
- **Idempotency**: A DNA sequence is never processed twice if it exists in `ledger.json` with a terminal outcome.
- **Atomicity**: `toSequence_parsed.json`, `toSequence_parsed.csv`, and `ledger.json` are updated "all-or-nothing".
- **Naming**: The canonical ledger is `data/ledger.json`. DNA strings are consistently referred to as `dna_sequence` in logs.

## Logs (JSON_LOG)
- `start`: Emitted when the batch starts.
- `process_item`: Emitted for each sequence with `outcome`, `dna_sequence`, and `latency_ms`.
- `complete`: Emitted when the batch finishes successfully.
- `correlation_id`: Propagated throughout the chain.

## Done When
- [x] Syntax errors (IndentationError) are resolved.
- [x] Ledger filename is standardized to `ledger.json`.
- [x] Persistence is atomic via `tempfile` and `os.replace`.
- [x] Ledger updates are deferred until successful output write.
- [x] Structured logging includes `correlation_id` and `latency_ms`.
