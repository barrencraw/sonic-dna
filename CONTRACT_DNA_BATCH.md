# Mini-Contract: DNA Batch Atomic Commit

## Trigger
- Called by `main.py` (watcher or `--once`) or directly.

## Inputs
- `data/raw/toSequence.txt`
- Existing `data/processed_ledger.json`
- Existing `data/output/toSequence_parsed.json` / `.csv`

## Win Condition (Done When)
- `utils/dna_ui.py` is syntactically valid.
- JSON, CSV, and Ledger updates are committed together using a temporary directory + `os.replace`.
- If any write or rename fails, NO files are modified in `data/output/` or `data/processed_ledger.json`.
- Redundant non-atomic write blocks are removed.
- Tests (`test_atomicity.py`, `test_idempotency.py`) pass.

## Error Classes
- `RuleParseError`: DNA string is invalid (caught per item).
- `RuleLoadError`: Cannot load rules (terminal).
- `PersistenceError`: Disk I/O or rename failed (terminal).

## Atomicity Boundary
- The "commit" happens at the end of `main()` in `dna_ui.py` after all processing.
- Files: `toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`.

## Telemetry Grep Recipe
\`\`\`bash
# Find batch start, item processing, and final outcomes
grep -E "\[Batch Start\]|\[Idempotency\]|\[Terminal Outcome\]" data/output/logs.txt
\`\`\`
