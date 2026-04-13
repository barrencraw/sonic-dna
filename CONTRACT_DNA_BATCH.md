# Chain Contract: DNA Batch Parsing

## Trigger
- Execution of `utils/dna_ui.py` or `main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: Raw DNA strings, one per line.
- `rules/*.json`: Rule definitions for the `DNACalculator`.
- `data/processed_ledger.json`: Persistence ledger tracking processed DNA.

## Terminal States
- `SUCCESS`: All new DNA strings processed and committed to output and ledger.
- `NO_NEW_DNA`: No new strings found in input that aren't already in the ledger.
- `PARTIAL_SUCCESS`: Some strings encountered `RuleParseError`, but these were recorded in the ledger and outputs; state is consistent.
- `ERROR`: Critical failure (e.g., `PersistenceError`, `RuleLoadError`); no state changes committed.

## Invariants
- **Idempotency**: A DNA string present in the ledger must not be parsed again.
- **Sync**: The ledger, JSON output, and CSV output must be updated together or not at all (Atomic Commit).
- **Format**: Output JSON must be a list of objects; CSV must have headers matching the union of all parsed fields.

## Error Classes
- `RuleLoadError`: Failed to load JSON rules from the rules directory.
- `DNAProcessingError`: Generic failure during the processing loop.
- `PersistenceError`: Failed to write or move files during the atomic commit phase.
- `RuleParseError`: Failed to parse a specific DNA string (handled per-item).

## Idempotency Key
- The raw DNA string itself.

## Atomicity Boundary
- The "Commit" phase using `os.replace` on all three files (JSON, CSV, Ledger) after successfully writing them to a temporary directory.

## Required Logs
- `[Idempotency] key=<DNA> dedupe_hit=<bool> terminal_outcome=<outcome>`
- `[OK] Processed <N> new DNA strings. Total in ledger: <M>`
