# DNA Batch Processing Chain Contract

## Goal
Ensure DNA batch processing is idempotent, atomic, and robust to environment variations (e.g., missing dependencies).

## Trigger
- Appending DNA strings to `data/raw/toSequence.txt` while `main.py` is running (watcher).
- Running `python3 main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.
- `rules/*.json`: Variable definitions for parsing.
- `data/processed_ledger.json`: Record of previously processed DNA.

## Terminal States
- `success`: DNA parsed and recorded.
- `error`: DNA failed parsing, error recorded in ledger/outputs.
- `refusal`: (Optional) System-level refusal to process.

## Invariants
- If the batch process finishes, either ALL outputs (JSON, CSV, Ledger) are updated, or NONE are (atomic commit).
- `toSequence.txt` is only cleared if the batch process completes successfully.
- No DNA string is processed twice if it exists in the ledger (idempotency).

## Idempotency Key
- The raw DNA string itself.

## Atomicity Boundary
- All three persistence files:
    - `data/output/toSequence_parsed.json`
    - `data/output/toSequence_parsed.csv`
    - `data/processed_ledger.json`
- Implemented via a temporary directory and `os.replace`.

## Required Logs
- `[Watcher]` or `[Once-Runner]` start.
- `[Idempotency] key=... dedupe_hit=True|False terminal_outcome=...`
- `[OK] Processed X new DNA strings.`
- `[ERROR]` or `[CRITICAL]` for failures.

## Grep Recipes (Triage)
- **Check for processing errors:** `grep "terminal_outcome=error" data/processed_ledger.json` (or logs)
- **Verify idempotency hits:** `grep "dedupe_hit=True" logs`
- **Check batch summary:** `grep "\[OK\] Processed" logs`
- **Triage critical failures:** `grep "\[CRITICAL\]" logs`
