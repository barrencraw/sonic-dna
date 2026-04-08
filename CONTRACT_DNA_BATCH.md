# DNA Batch Parsing Chain Contract

## Trigger
- Append new DNA strings to `data/raw/toSequence.txt`.
- Manual run via `python3 main.py --once`.

## Inputs
- DNA strings (e.g., `VOL08900750712`).

## Terminal States
- `success`: DNA parsed and results recorded.
- `error: <msg>`: DNA malformed or no rule found.
- `dedupe_hit`: DNA already processed (skipped).

## Invariants
- `data/processed_ledger.json` contains every DNA string successfully or unsuccessfully processed.
- No duplicate DNA strings in the cumulative outputs.
- Atomicity: JSON, CSV, and Ledger are updated together or not at all.

## Error Classes
- `RuleParseError`: Individual DNA string is invalid.
- `RuleLoadError`: System-wide failure to load rules.
- `PersistenceError`: IO failure during atomic commit.

## Idempotency Key
- The raw DNA string itself.

## Atomicity Boundary
- The "Unified Atomic Commit" in `utils/dna_ui.py`: stages JSON, CSV, and Ledger in a temp directory and replaces them sequentially.

## Required Logs
- `[Idempotency][<correlation_id>] key=<dna> dedupe_hit=<bool> terminal_outcome=<outcome>`
- `[OK][<correlation_id>] Processed <n> new DNA strings.`

## Grep Recipes for Telemetry Triage
- **Find all failures:** `grep "terminal_outcome=error" data/processed_ledger.json` (or check logs)
- **Trace a specific batch:** `grep "<correlation_id>" observability.log` (if redirected) or stdout.
- **Identify dedupe hits:** `grep "dedupe_hit=True" stdout`
