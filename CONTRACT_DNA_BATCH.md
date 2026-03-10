# Contract: DNA Batch Parsing

## Description
The DNA Batch Parsing chain is responsible for reading raw DNA strings from `data/raw/toSequence.txt`, parsing them using modular rule definitions, and appending the results to cumulative JSON and CSV output files. It maintains an idempotency ledger to ensure each unique DNA string is processed exactly once.

## Chain Specification

- **Trigger**: New non-empty content detected in `data/raw/toSequence.txt` (Watcher) or manual execution via `python main.py --once`.
- **Inputs**:
    - `data/raw/toSequence.txt`: A newline-delimited file of DNA strings.
    - `rules/*.json`: Rule definitions for various audio properties.
- **Terminal States**:
    - `SUCCESS`: DNA string was parsed and output was committed.
    - `ERROR`: Parsing or persistence failed for a specific DNA string.
    - `DEDUPE`: DNA string was already processed (exists in ledger).
- **Invariants**:
    - **Per-String Idempotency**: Each unique DNA string in the input is processed exactly once across the system's lifetime.
    - **Atomic Persistence**: JSON output, CSV output, and the idempotency ledger are updated as a single atomic unit. No partial writes are allowed.
    - **Cumulative Outputs**: New results are appended to existing `toSequence_parsed.json` and `toSequence_parsed.csv` files.
- **Error Classes**:
    - `RuleLoadError`: Failed to load rule definitions from the `rules/` directory.
    - `RuleParseError`: A specific DNA string failed to match its defined rule structure or range.
    - `PersistenceError`: Failed to write output files atomically to disk.
- **Idempotency Key**: The raw DNA string itself.
- **Atomicity Boundary**: The update of `toSequence_parsed.json`, `toSequence_parsed.csv`, and `data/processed_ledger.json`.
- **Required Logs**:
    - All logs must be prefixed with `[OBSERVABILITY]`.
    - Fields: `correlation_id`, `actor_id`, `chain_name`, `step`, `outcome`, `idempotency_key`, `latency_ms`.
    - Events: Start of batch, start of per-string processing, transition to terminal outcome, and end of batch.

## Grep Recipes for Triage
- `grep "\[OBSERVABILITY\]" output.log`
- `grep "terminal_outcome=ERROR" output.log`
