# Chain Contract: DNA Batch Processing

## Trigger
- Manual execution of `main.py --once`.
- File system event detected by `watch_loop` in `main.py` on `data/raw/toSequence.txt`.

## Inputs
- `data/raw/toSequence.txt`: Raw DNA strings, one per line.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Idempotency ledger.

## Terminal States
- `SUCCESS`: All new DNA strings processed and persisted.
- `ERROR`: Fatal failure (e.g., rule load error, input read error).
- `PARTIAL`: Some items failed parsing, but were recorded in the ledger and outputs.

## Invariants
- A DNA string in the ledger with a terminal outcome (`success` or `error:*`) is never re-processed.
- Outputs (`.json`, `.csv`, `ledger.json`) are updated atomically as a single unit of work.
- Output files are only modified if at least one new DNA string is processed.

## Error Classes
- `RuleLoadError`: Failed to load rules from disk.
- `DNAProcessingError`: Generic processing failure.
- `PersistenceError`: Atomic write phase failed.
- `RuleParseError`: Individual DNA string failed to match rules.

## Idempotency Key
- The raw DNA string itself.

## Atomicity Boundary
- The `os.replace` calls at the end of the batch processing loop in `utils/dna_ui.py`.

## Required Logs
- `[Idempotency] key=<DNA> dedupe_hit=<bool> terminal_outcome=<outcome>`
- `[OK] Processed <count> new DNA strings.`

## Grep Recipe
To verify idempotency hits:
```bash
grep "dedupe_hit=True" logs.txt
```
To verify terminal outcomes:
```bash
grep "terminal_outcome=" logs.txt
```
