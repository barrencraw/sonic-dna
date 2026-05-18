# CONTRACT: DNA Batch Parser

## Trigger
- Content detected in `data/raw/toSequence.txt` (via `main.py` watcher or `--once` flag).

## Inputs
- `dna_sequence`: A raw DNA string (e.g., `VOL08900750712`).

## Terminal States
- `SUCCESS`: DNA string parsed successfully; result appended to JSON/CSV.
- `PARSE_ERROR`: DNA string failed validation; error message recorded in JSON/CSV.
- `SKIPPED`: DNA string already present in `processed_ledger.json` (idempotency hit).

## Invariants
- No DNA sequence is processed twice (enforced by `processed_ledger.json`).
- Output files (`.json`, `.csv`) and the ledger are updated atomically via sequential `os.replace`.
- The input file `toSequence.txt` is cleared only after a successful batch completion.

## Error Classes
- `RuleLoadError`: Critical failure to load rule definitions from `rules/`.
- `RuleParseError`: Individual DNA string does not match rule schema.
- `PersistenceError`: Atomic commit (write/rename) failed or existing data could not be loaded securely.

## Idempotency
- **Key**: Raw `dna_sequence` string.
- **Storage**: `data/processed_ledger.json`.

## Atomicity Boundary
- All changes to `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` are committed via `os.replace` from a temporary directory. The ledger is renamed last to commit the batch.

## Required Logs
- `[Idempotency] key=<DNA> dedupe_hit=<True|False> terminal_outcome=<outcome>`

---

## Telemetry Grep Recipes

### Find all deduplication hits
`grep "dedupe_hit=True" logs/dna_batch.log` (if logs are redirected)

### Count successful parses in a batch
`grep "terminal_outcome=SUCCESS" logs/dna_batch.log | wc -l`

### Identify specific parse errors
`grep "terminal_outcome=PARSE_ERROR" logs/dna_batch.log`
