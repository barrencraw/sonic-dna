# Contract: DNA Batch Parsing Chain

## Trigger
- New DNA strings detected in `data/raw/toSequence.txt`.

## Inputs
- `data/raw/toSequence.txt`: A text file containing one DNA string per line (e.g., `VOL08900750712`).
- `rules/*.json`: Rule definitions for parsing DNA.
- `data/processed_ledger.json`: Idempotency ledger.
- `data/output/toSequence_parsed.json/csv`: Cumulative output stores.

## Outputs / Side Effects
- `data/output/toSequence_parsed.json`: Appended with new parsed results.
- `data/output/toSequence_parsed.csv`: Appended with new parsed results (flattened).
- `data/processed_ledger.json`: Updated with new DNA keys and terminal outcomes.
- `data/raw/toSequence.txt`: Truncated (emptied) ONLY upon successful commit of outputs.

## Terminal States
- `SUCCESS`: DNA string parsed and committed.
- `ERROR: <detail>`: DNA string failed parsing; error recorded in outputs and ledger.

## Invariants
- **Idempotency**: A DNA string already present in the ledger with a terminal outcome MUST NOT be re-processed or added to outputs again.
- **Atomicity**: Updates to the JSON output, CSV output, and Ledger MUST be atomic. If one fails, none should be updated.
- **Durable Persistence**: All writes must be flushed and synced to disk before renaming (committing).

## Observability
- Required Logs:
  - `[Idempotency] key=<dna> dedupe_hit=<bool> terminal_outcome=<outcome>`
  - `[OK] Processed <n> new DNA strings.`
- Errors must be classified (e.g., `RuleLoadError`, `PersistenceError`).

## Telemetry Triage (Grep Recipe)
- `grep -E "\[Idempotency\]|\[OK\]|\[ERROR\]" output.log`
