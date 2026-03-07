# Chain Contract: DNA Batch Parsing

## Trigger
Watcher in `main.py` detects new content in `data/raw/toSequence.txt`, or `main.py --once` is invoked.

## Inputs
- `data/raw/toSequence.txt`: One DNA string per line.
- `rules/`: Directory of JSON rule definitions.
- `data/processed_ledger.json`: Idempotency ledger.

## Terminal States
- **SUCCESS**: All DNA strings processed, output files updated, ledger updated, input file cleared.
- **ERROR**: One or more critical failures (I/O, rule load); state rolled back (output files and ledger unchanged), input file preserved.
- **DEDUPE**: DNA string already in ledger; skipped without redundant work.

## Invariants
- Atomic updates: JSON output, CSV output, and Processed Ledger must be updated as a single unit.
- Consistency: `toSequence.txt` must ONLY be cleared if the atomic update of all three files succeeds.
- No partial writes: Interrupted processing should leave no truncated or corrupted files.

## Error Classes
- `RuleLoadError`: Rules folder or files missing/malformed.
- `RuleParseError`: DNA string doesn't match rules (non-terminal for the batch, but recorded as error entry).
- `PersistenceError`: Atomic rename or I/O failure.

## Idempotency
- Key: DNA string.
- Ledger: `data/processed_ledger.json`.

## Atomicity Boundary
- All output persistence (JSON, CSV, Ledger) happens inside an `os.replace` (atomic rename) loop or similar commit pattern.

## Required Logs (Prefix: [OBSERVABILITY])
- Start: `chain=dna_batch_parsing status=start correlation_id=<uuid>`
- Idempotency check: `step=idempotency_check key=<dna> hit=<true|false>`
- Step Outcome: `step=parse_dna key=<dna> outcome=<success|error>`
- Terminal: `chain=dna_batch_parsing status=success|error correlation_id=<uuid> new_processed=<count>`

## Grep Recipes
- **Follow a specific chain:** `grep "correlation_id=<uuid>" logs.txt`
- **Triage failures:** `grep "status=error" logs.txt`
- **Check deduplication rate:** `grep "hit=true" logs.txt | wc -l`
