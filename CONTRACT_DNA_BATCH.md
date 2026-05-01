# Chain Contract: DNA Batch Parsing

## Overview
This chain manages the cumulative parsing of audio DNA strings into structured JSON and CSV datasets, ensuring idempotency and atomic persistence.

## Done When
- [ ] DNA Batch Parsing is fully atomic across JSON, CSV, and Ledger.
- [ ] `utils/dna_ui.py` has no syntax errors and passes `py_compile`.
- [ ] Idempotency is maintained (no redundant processing of already-ledgered strings).
- [ ] Every processing attempt logs clear `[Idempotency]` and `[Terminal Outcome]` lines.
- [ ] Adversarial tests for rename failures pass, proving ledger-backed recovery.

## Contract Details

### Trigger
- **Watcher (`main.py`)**: Background loop monitoring `data/raw/toSequence.txt`.
- **CLI (`main.py --once`)**: Manual invocation for batch processing.

### Inputs
- `data/raw/toSequence.txt`: Newline-delimited list of raw DNA strings.
- `rules/*.json`: Schema definitions for DNA parsing.
- `data/processed_ledger.json`: Persistence of already-processed strings.

### Terminal States
- `SUCCESS`: All new strings processed and results committed to disk.
- `PARTIAL_SUCCESS`: Some strings failed parsing (recorded as errors in output), but the batch was committed.
- `ERROR`: Infrastructure or persistence failure; no state changes committed.
- `NO_NEW_DNA`: Input was empty or all strings were already in the ledger.

### Invariants
1. **Idempotency**: A DNA string already present in `processed_ledger.json` will not be processed again or appended to output files.
2. **Atomicity (Ledger-Backed Recovery)**: `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` are updated in sequence. The **ledger is always updated last**. This ensures that if the process crashes mid-update, the next run will detect missing ledger entries and safely re-process/re-append data.
3. **Consistency**: The ledger reflects the successful completion of the parsing and persistence transaction.

### Error Classes
- `RuleLoadError`: Fails if rules folder is missing or invalid.
- `RuleParseError`: Item-level failure; parsing a specific DNA string fails (non-terminal for the batch).
- `PersistenceError`: Terminal failure writing output files (e.g., disk full, permissions).

### Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

### Atomicity Boundary
- The "Commit" phase in `utils/dna_ui.py`. Files are prepared in a temp directory and then moved to their destinations. The ledger move is the final "Commit Point".

### Required Logs (Telemetry)
Each processing attempt must log:
- `[Batch Start] Processing DNA strings...`
- `[Idempotency] key=<DNA> dedupe_hit=<True/False> terminal_outcome=<outcome>`
- `[Terminal Outcome] <SUCCESS/PARTIAL_SUCCESS/ERROR/NO_NEW_DNA>`
- `[OK] Processed <N> new DNA strings.`

## Triage & Observability (Grep Recipes)
- **Check for deduplications**: `grep "dedupe_hit=True" logs.txt`
- **Check for parsing errors**: `grep "terminal_outcome=error" logs.txt`
- **Check for batch success**: `grep "\[Terminal Outcome\] SUCCESS" logs.txt`
- **Check for persistence failures**: `grep "PersistenceError" logs.txt`
- **Find results for specific DNA**: `grep "key=VOL08900750712" logs.txt`
