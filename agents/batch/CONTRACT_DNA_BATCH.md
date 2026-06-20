# DNA Batch Chain Contract

## Trigger
New non-empty content detected in `data/raw/toSequence.txt`.

## Inputs
- `data/raw/toSequence.txt`: Raw DNA strings (one per line).
- `data/processed_ledger.json`: Historical record of processed DNA strings.
- `data/output/toSequence_parsed.json`: Cumulative JSON output.
- `data/output/toSequence_parsed.csv`: Cumulative CSV output.

## Terminal States
- `success`: DNA string parsed and added to outputs.
- `error: <message>`: DNA string failed parsing (e.g., malformed); recorded as error in outputs.
- `skipped`: DNA string already present in ledger; no side effects.

## Invariants
- Each unique DNA string appears only once in `toSequence_parsed.json` and `toSequence_parsed.csv`.
- `toSequence_parsed.json` and `toSequence_parsed.csv` remain in sync.
- The `processed_ledger.json` is only updated when the corresponding output files are successfully written.

## Error Classes
- `RuleLoadError`: Rules folder missing or corrupt.
- `RuleParseError`: Individual DNA string is malformed.
- `PersistenceError`: I/O failure during atomic commit (disk full, permissions).

## Idempotency Key
The DNA string itself (e.g., `VOL08900750712`).

## Atomicity Boundary
The simultaneous update of:
1. `data/output/toSequence_parsed.json`
2. `data/output/toSequence_parsed.csv`
3. `data/processed_ledger.json`

Implementation uses `tempfile.TemporaryDirectory` + `os.replace` + `os.fsync` for all-or-nothing "commit" semantics.

## Required Logs
- Start/Step/End logs with `key` and `terminal_outcome`.
- `[Idempotency]` prefix for deduplication hits.
- `[OK]` prefix for successful batch completion.
- `[ERROR]` or `[CRITICAL]` for processing or persistence failures.
