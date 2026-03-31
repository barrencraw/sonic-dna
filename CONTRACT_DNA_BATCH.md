# DNA Batch Parsing Chain Contract

## Win Condition
A robust, idempotent DNA batch processing chain with an atomic commit boundary that incorporates system integrity (fatigue) logic and standardized structured observability logs.

## Chain Details
- **Trigger**: `main.py` (watcher or once-runner) calls `utils.dna_ui.main()`.
- **Inputs**: `data/raw/toSequence.txt` (one DNA string per line).
- **Terminal States**:
    - `SUCCESS`: DNA parsed correctly and results appended.
    - `ERROR`: Parsing failed (recorded in ledger/outputs).
    - `SKIPPED`: DNA already in ledger.
    - `REFUSAL`: Integrity at 0; processing halted (not recorded in ledger).
- **Invariants**:
    - **Atomicity**: The processed ledger, integrity state, and JSON/CSV outputs must be updated in a single atomic commit boundary.
    - **Idempotency**: Processing the same DNA string multiple times must not result in duplicate entries in outputs or multiple wear applications.
    - **Integrity**: Non-maintenance DNA processing is halted if system integrity is 0.
- **Error Classes**:
    - `RuleLoadError`: Failure to load rule definitions.
    - `DNAProcessingError`: General failure during the processing loop.
    - `PersistenceError`: Atomic commit failure.
- **Idempotency Key**: The raw DNA string.
- **Atomicity Boundary**: All outputs staged in a temporary directory and moved into place via `os.replace`.
- **Required Logs**:
    - `[START]`, `[STEP]`, `[Idempotency]`, `[OK]`, `[END]`
    - `[OBSERVABILITY] {json}` for all major events (start, parse, refusal, end).

## Triage Grep Recipes
- Failures: `grep -E "\[ERROR\]|outcome=error"`
- Specific DNA: `grep "key=..."`
- Idempotency Hits: `grep "dedupe_hit=True"`
- Run Summaries: `grep -E "\[START\]|\[OK\]|\[END\]"`
- Observability: `grep "\[OBSERVABILITY\]"`
