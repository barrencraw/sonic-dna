# DNA Batch Parsing Contract

## Overview
Hardened contract for the DNA processing chain, ensuring atomicity, idempotency, and observability.

## Chain Definition
- **Trigger:** `main.py` watcher or CLI `--once`.
- **Inputs:**
    - `data/raw/toSequence.txt` (Drained queue)
    - `rules/*.json` (Domain rules)
    - `data/processed_ledger.json` (Idempotency ledger)
- **Outputs:**
    - `data/output/toSequence_parsed.json` (Cumulative JSON)
    - `data/output/toSequence_parsed.csv` (Cumulative CSV)
    - `data/processed_ledger.json` (Updated ledger)
- **Terminal States:** `SUCCESS`, `ERROR`, `DEDUPE`.

## Invariants
1. **Atomic Persistence:** All three output files (JSON, CSV, Ledger) must be updated together or not at all.
2. **At-Most-Once Truncation:** `toSequence.txt` is only cleared if persistence succeeds.
3. **Idempotency:** Re-processing the same DNA string must not result in duplicate entries in JSON/CSV.
4. **Consistency:** JSON and CSV outputs must contain the same processed records.

## Error Classes
- `RuleLoadError`: Rules folder missing or malformed JSON.
- `RuleParseError`: DNA string does not match any rule or has invalid format.
- `PersistenceError`: Failure during atomic write/commit phase (e.g., Disk Full, Permissions).

## Observability
- **Logs:** JSON logs prefixed with `[OBSERVABILITY]`.
- **Required Fields:** `correlation_id`, `step`, `outcome`, `latency_ms`, `idempotency_key`.

## Atomicity Implementation
- Use `tempfile.TemporaryDirectory` in the destination folder.
- Write all three files to the temp dir.
- `os.fsync` all files.
- `os.replace` (atomic rename) to final destinations.
- Truncate input file.
