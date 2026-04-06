# Chain Contract: DNA Batch Parsing

## Trigger
- CLI: `python3 main.py --once`
- Watcher: Detection of new content in `data/raw/toSequence.txt`

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Idempotency tracking.

## Terminal States
- `success`: DNA parsed correctly.
- `error: <message>`: DNA parsing failed (e.g., malformed string).
- `skipped`: Batch run exited before completion (e.g., empty input).

## Invariants
- `toSequence.txt` is only cleared if the entire batch process completes successfully.
- Every processed DNA string must have an entry in `processed_ledger.json`.
- `toSequence_parsed.json` and `toSequence_parsed.csv` must stay in sync with the ledger.

## Error Classes
- `DNAProcessingError`: Generic processing failure.
- `RuleLoadError`: Failed to load or parse a JSON rule.
- `PersistenceError`: Failed to write output files atomically.

## Idempotency Key
- The raw DNA string itself.

## Atomicity Boundary
- The "Atomic Write Pattern" in `utils/dna_ui.py`: All outputs (JSON, CSV, Ledger) are staged in a temp directory and committed via `os.replace`.

## Required Logs
- `[START] DNA Batch Parsing`
- `[Idempotency] key=... dedupe_hit=... terminal_outcome=...`
- `[STEP] Parsing DNA: ...`
- `[OK] Processed ...`
- `[END] DNA Batch Parsing`

---

## Telemetry Grep Recipes

### Find all failures in the last run:
`grep "terminal_outcome=error" logs.txt`

### Check if a specific DNA string was processed:
`grep "key=VOL0890" logs.txt`

### Verify idempotency hits:
`grep "dedupe_hit=True" logs.txt`

### Summary of batch run:
`grep -E "\[START\]|\[OK\]|\[END\]" logs.txt`
