# DNA Batch Parsing Chain Contract

## Goal (Win Condition)
A robust, idempotent, and atomic DNA batch processing chain. It must process any number of DNA strings, record their outcomes in a persistent ledger, and ensure that results are never partially committed (JSON, CSV, and Ledger must all update as one atomic unit).

## Triage / Win Condition
- **Success:** All new DNA strings are parsed and results are consistently reflected in JSON, CSV, and the ledger.
- **Deduplication:** Repeated DNA strings are skipped using the ledger to avoid redundant CPU/IO.
- **Atomicity:** A crash at any point results in either "nothing changed" or "everything updated" for each batch commit.
- **Done When:**
    - `utils/dna_ui.py` uses a temporary directory for atomic renames of JSON, CSV, AND the ledger.
    - Idempotency hits are logged with `[Idempotency]`.
    - Chain starts/ends are logged with `[START]` and `[END]`.
    - `test_atomicity.py` passes, including failures during rename.

### Telemetry Triage (Grep Recipes)
- **Check for failures:** `grep -E "\[ERROR\]|\[Once‐Runner\]\[CRITICAL\]" logs/output.log`
- **Track a specific DNA:** `grep "key=VOL08900750712" logs/output.log`
- **Check for idempotency hits:** `grep "dedupe_hit=True" logs/output.log`
- **Verify run summary:** `grep -E "\[START\]|\[OK\]|\[END\]" logs/output.log`

## Chain Details
- **Trigger:** `main.py` (Watcher or Once-Runner) calls `run_batch(correlation_id=...)`.
- **Inputs:** `data/raw/toSequence.txt` (one DNA string per line).
- **Terminal States:**
    - `SUCCESS`: DNA string parsed successfully.
    - `ERROR`: Rule calculation failed (e.g., `RuleParseError`).
    - `SKIPPED`: DNA string already present in the ledger.
- **Invariants:**
    - The ledger always contains the terminal outcome of every processed DNA.
    - `toSequence_parsed.json` and `.csv` are always in sync with the ledger.
- **Idempotency Key:** The DNA string itself.
- **Atomicity Boundary:**
    - `data/processed_ledger.json`
    - `data/output/toSequence_parsed.json`
    - `data/output/toSequence_parsed.csv`

## Required Logs (Structured)
- `[START] dna_batch_chain correlation_id=...`
- `[Idempotency] key=... dedupe_hit=True terminal_outcome=... correlation_id=...`
- `[Idempotency] key=... dedupe_hit=False terminal_outcome=processing correlation_id=...`
- `[STEP] Parsing DNA: ... correlation_id=...`
- `[OK] Processed ... new DNA strings. Total in ledger: ... correlation_id=...`
- `[END] dna_batch_chain correlation_id=...`
