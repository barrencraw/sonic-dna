# DNA Batch Parsing Chain Contract

## Goal
Reliably process batches of DNA strings from a raw input file into structured cumulative JSON and CSV outputs, ensuring that each string is only processed once (idempotency) and that all output artifacts are committed together (atomicity).

## Triage
**Win Condition:** One-time or background parsing that never produces duplicate entries, never leaves half-written files, and always reflects the correct processing state in a ledger.

**Completion Checklist:**
- [x] Correctly handle missing or empty input files.
- [x] Maintain a persistent ledger of processed DNA strings.
- [x] Atomic write pattern for JSON, CSV, and Ledger.
- [x] Clear input file only after successful batch commit.
- [x] Log key events (Idempotency check, Success/Error outcomes).

## Details

### Trigger
- **Manual:** `python3 main.py --once`
- **Automatic:** `main.py` watcher detects changes in `data/raw/toSequence.txt`.

### Inputs
- `data/raw/toSequence.txt`: Newline-separated DNA strings.
- `rules/*.json`: Variable parsing rules.

### Terminal States
- `success`: DNA parsed correctly and added to outputs.
- `error: <message>`: DNA failed to parse; error recorded in outputs.
- `skipped`: DNA already present in ledger; no action taken.

### Invariants
- JSON output, CSV output, and Ledger must remain synchronized.
- The raw input file is only cleared if the batch commit succeeds.
- No partial/torn writes to disk on failure.

### Error Classes
- `DNAProcessingError`: Generic processing failure.
- `RuleLoadError`: Failed to load JSON rules from disk.
- `PersistenceError`: Failed to write or commit output files atomically.

### Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

### Atomicity Boundary
- `data/output/toSequence_parsed.json`
- `data/output/toSequence_parsed.csv`
- `data/processed_ledger.json`

### Required Logs
- `[Idempotency] key=<DNA> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `[OK] Processed <N> new DNA strings. Total in ledger: <M>`
- `[ERROR] <message>` or `[CRITICAL] <message>`

## Telemetry Triage (Grep Recipes)
- **Check for failures:** `grep -E "\[ERROR\]|\[CRITICAL\]|terminal_outcome=error" logs.txt`
- **Check idempotency hits:** `grep "dedupe_hit=True" logs.txt`
- **Verify successful runs:** `grep "\[OK\] Processed" logs.txt`
