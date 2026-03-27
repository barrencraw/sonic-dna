# DNA Batch Parsing Chain Contract

## Trigger
- **Watcher (`main.py`)**: Automatic trigger on change to `data/raw/toSequence.txt`.
- **Once-Runner (`main.py --once`)**: Manual CLI trigger.

## Inputs
- `data/raw/toSequence.txt`: New DNA strings (one per line).
- `data/processed_ledger.json`: Persistent idempotency ledger.
- `data/output/toSequence_parsed.json`: Cumulative JSON output.
- `data/output/toSequence_parsed.csv`: Cumulative CSV output.

## Terminal States
- `SUCCESS`: All DNA strings processed and committed atomically.
- `ERROR`: Process halted due to critical I/O or logic error; no outputs committed.
- `SKIPPED`: DNA already in ledger; no redundant computation or I/O.

## Invariants
- **Atomicity Boundary**: The update of the ledger (`data/processed_ledger.json`), JSON output (`toSequence_parsed.json`), and CSV output (`toSequence_parsed.csv`) must be committed as a single atomic unit using an atomic rename pattern.
- **Idempotency**: Identical DNA strings (keys) must not produce duplicate entries in JSON/CSV outputs if they already exist in the ledger.
- **Data Integrity**: Truncation of `toSequence.txt` only occurs if the batch parser reports SUCCESS.

## Error Classes
- `DNAProcessingError`: Generic processing failure.
- `RuleLoadError`: Critical failure to load DNA rules.
- `PersistenceError`: Atomic rename or write failure.
- `RuleParseError`: Domain-level DNA syntax error (logged per-DNA, doesn't halt batch).

## Required Logs
- `[START] dna_batch_chain`
- `[STEP] processing_dna key=...`
- `[Idempotency] key=... dedupe_hit=... terminal_outcome=...`
- `[OK] Parsed DNA count=...`
- `[END] dna_batch_chain outcome=...`
- `[ERROR]` with traceback on critical failures.

## Telemetry Triage (Grep Recipe)
- **Check for failures**: `grep -E "\[ERROR\]|outcome=error" logs.txt`
- **Track specific DNA string**: `grep "key=YOUR_DNA_HERE" logs.txt`
- **Verify Idempotency hits**: `grep "dedupe_hit=True" logs.txt`
- **Summary of run**: `grep -E "\[START\]|\[OK\]|\[END\]" logs.txt`
