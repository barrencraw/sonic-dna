# Chain Contract: DNA Batch Parsing

## Overview
Hardened batch processing of DNA strings from `data/raw/toSequence.txt` into cumulative JSON and CSV datasets.

## Contract
- **Trigger**: File watcher in `main.py` detects changes in `data/raw/toSequence.txt`, or CLI invocation via `python3 main.py --once`.
- **Inputs**:
    - `data/raw/toSequence.txt`: New DNA strings (newline-separated).
    - `data/processed_ledger.json`: Idempotency ledger of already processed DNA.
- **Terminal States**:
    - `SUCCESS`: DNA string parsed and added to cumulative output.
    - `ERROR`: DNA string failed validation or parsing; recorded in output as error.
    - `SKIPPED`: DNA string already present in ledger or current batch (idempotency hit).
    - `NO_NEW_DNA`: Input file was empty or all strings were duplicates.
- **Invariants**:
    - Every DNA string in the output JSON/CSV must have a corresponding entry in the ledger.
    - The input file `toSequence.txt` is only cleared if the batch commit succeeds.
    - No duplicate DNA strings are ever processed within the same batch.
- **Error Classes**:
    - `RuleLoadError`: Critical failure to load rules from disk.
    - `PersistenceError`: Atomic write failure (disk full, permissions).
    - `RuleParseError`: Non-critical; individual DNA string failed parsing.
- **Idempotency Key**: The raw DNA string.
- **Atomicity Boundary**: Unified atomic rename for `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json`.
- **Required Logs (Structured)**:
    - `step=init outcome=START`
    - `step=idempotency_check outcome=SKIPPED key={dna}`
    - `step=parse_dna outcome=SUCCESS|ERROR key={dna}`
    - `step=atomic_commit outcome=SUCCESS|ERROR`
    - `step=batch_complete outcome=END`

## Triage Grep Recipes
- `grep "outcome=SKIPPED" log.txt` - Check for idempotency hits.
- `grep "outcome=ERROR" log.txt` - Find parsing or persistence failures.
- `grep "CRITICAL" log.txt` - Identify infra failures in watcher/once-runner.
- `grep "step=batch_complete" log.txt` - Run summaries.
