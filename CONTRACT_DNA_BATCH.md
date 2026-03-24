# DNA Batch Parsing Contract

## Trigger
- **Watcher:** Automated process monitoring `data/raw/toSequence.txt`.
- **Once-Runner:** Manual CLI execution via `python3 main.py --once`.

## Inputs
- **DNA Strings:** List of DNA strings (one per line) in `data/raw/toSequence.txt`.
- **Rules:** JSON rule definitions in `rules/`.
- **Existing Data:** Cumulative JSON/CSV outputs and a processed ledger in `data/`.

## Terminal States
- `SUCCESS`: Batch completed successfully.
- `ERROR`: A critical failure occurred during rule loading, input reading, or output persistence.
- `NO_NEW_DNA`: The input file was empty or all strings were already in the ledger.

## Invariants
- **Idempotency:** A DNA string already in the ledger will not be re-processed.
- **Atomicity:** All outputs (JSON, CSV, Ledger) are committed together using a temporary directory and atomic renames. The input file is only cleared if the process succeeds.
- **Deduplication:** The ledger is the single source of truth for processed DNA.

## Error Classes
- `RuleLoadError`: Rules folder or specific JSON rules are invalid.
- `DNAProcessingError`: General error reading input or parsing DNA.
- `PersistenceError`: Error writing or renaming output files.

## Required Logs (Observability)
- `start_batch`: When the chain begins.
- `process_dna`: For each DNA string (includes `idempotency_key`, `outcome`, `latency_ms`).
- `complete_batch`: When the batch finishes (includes `latency_ms`).
- `ERROR` logs: Include `error_msg` or `error` field in the JSON structure.

## Triage Recipe
```bash
grep -E "\[OBSERVABILITY\]|\[Idempotency\]"
```
