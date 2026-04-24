# DNA Batch Parsing Chain Contract

## Goal
Robust, atomic, and idempotent batch parsing of DNA strings from `toSequence.txt` into structured JSON and CSV formats.

## Contract details

### Trigger
- Manual execution of `utils/dna_ui.py` or via `main.py --once`.
- Background watcher (not covered by this specific contract, but uses the same logic).

### Inputs
- `data/raw/toSequence.txt`: A newline-delimited file of DNA strings.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Idempotency ledger.

### Outputs (Atomic Boundary)
All outputs must be committed together. If one fails, none should be updated.
- `data/output/toSequence_parsed.json`: Cumulative JSON results.
- `data/output/toSequence_parsed.csv`: Cumulative CSV results.
- `data/processed_ledger.json`: Updated idempotency ledger.

### Terminal States
- `SUCCESS`: All new DNA strings were processed successfully.
- `ERROR`: A critical infrastructure or rule loading error occurred.
- `PARTIAL_SUCCESS`: Some DNA strings were processed successfully, others failed parsing.
- `NO_NEW_DNA`: No new DNA strings were found (all deduplicated).
- `SKIPPED`: All found DNA strings were already in the ledger.

### Invariants
- **Idempotency**: Processing the same DNA string twice (same raw string) results in a dedupe hit; the second run does not add new entries to JSON/CSV.
- **Atomicity**: Partial writes are forbidden. JSON, CSV, and Ledger are updated in a single transaction.
- **Append-Only (Logical)**: JSON and CSV represent the cumulative state of all successful (and error-recorded) parses.

### Error Classes
- `RuleLoadError`: Failed to load rules from the rules folder.
- `PersistenceError`: Failed to write or commit output files.
- `DNAProcessingError`: General failure in the batch process.

### Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

### Required Logs (Telemetry)
All logs must include a `correlation_id` for the batch run.
- `[BATCH][START] correlation_id={id} count={n}`
- `[BATCH][STEP] key={idempotency_key} dedupe_hit={bool} terminal_outcome={outcome}`
- `[BATCH][COMMIT] correlation_id={id} status={terminal_state}`
- `[BATCH][END] correlation_id={id}`

## Grep Recipes
- Triage failures: `grep "| ERROR |" logs` (or similar)
- Check completion: `grep "\[BATCH\]\[COMMIT\]" logs`
- Follow a specific string: `grep "VOL08900750712" logs`
