# Chain Contract: DNA Batch Parsing

## Triage
- **Win Condition**: Robust, idempotent DNA batch processing with an atomic "all-or-nothing" commit boundary for JSON, CSV, and Ledger.
- **Done When**:
    - [x] Syntax error (IndentationError) in `utils/dna_ui.py` is resolved.
    - [x] Every processed DNA string is recorded in the ledger *during* the loop.
    - [x] The idempotency ledger is updated atomically with the JSON/CSV outputs.
    - [x] No duplicate entries are created in cumulative outputs on double-invocation.
    - [x] Regression tests for atomicity and idempotency pass.

## Trigger
- `utils.dna_ui.main()`: Triggered by the `main.py` watcher loop (when `data/raw/toSequence.txt` has new lines) or the `--once` runner.

## Inputs
- `data/raw/toSequence.txt`: Raw DNA strings, one per line.
- `rules/*.json`: Variable-specific parsing rules.
- `data/processed_ledger.json`: Idempotency ledger of already-calculated DNA.

## Terminal States
- **SUCCESS**: New DNA parsed and appended to cumulative JSON/CSV; ledger updated.
- **SKIPPED**: All DNA in input was already in the ledger.
- **ERROR**: Rule load, parse, or persistence failure. (Atomicity boundary ensures no partial updates).

## Invariants
- `data/processed_ledger.json` keys must match entries in `toSequence_parsed.json`.
- No duplicate DNA entries in cumulative outputs.
- Atomicity: JSON, CSV, and Ledger are updated together or not at all.

## Error Classes
- `RuleLoadError`: Rules folder missing or corrupted.
- `RuleParseError`: DNA string malformed or missing rule. (Logged to output, doesn't halt batch).
- `PersistenceError`: IO error during atomic write/commit.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- All cumulative artifacts (`data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`, `data/processed_ledger.json`) are committed via a `TemporaryDirectory` + `os.replace` pattern.

## Required Logs
- `[Idempotency] key=... dedupe_hit=True terminal_outcome=...`
- `[Idempotency] key=... dedupe_hit=False terminal_outcome=processing`
- `[OK] Processed ... new DNA strings.`
- `[ERROR] ...`

## Grep Recipes (Telemetry)
- **Check for deduplication:** `grep "dedupe_hit=True" logs.txt`
- **Check for success:** `grep "terminal_outcome=success" logs.txt`
- **Check for parse errors:** `grep "terminal_outcome=error" logs.txt`
- **Check for atomic commit success:** `grep "\[OK\] Processed" logs.txt`
