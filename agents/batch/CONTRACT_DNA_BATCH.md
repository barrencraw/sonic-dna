# DNA Batch Chain Contract

## Win Condition
Robust, idempotent, and thermally-protected DNA batch processing with full observability.

## Done When
- [ ] Multiple invocations of the same DNA string do not create duplicate entries in JSON/CSV.
- [ ] System heat is tracked and prevents processing beyond `MAX_HEAT` (10.0).
- [ ] All output writes (JSON, CSV, Ledger) are atomic via tempfile + rename.
- [ ] Telemetry includes `correlation_id` and `JSON_LOG:` prefix for all steps.
- [ ] All field names are standardized to `dna_sequence`.

## Contract Details

### Trigger
- **Watcher:** Filesystem change in `data/raw/toSequence.txt`.
- **Manual:** `--once` flag in `main.py`.

### Inputs
- File: `data/raw/toSequence.txt` (Newline-delimited DNA strings).
- State: `data/ledger.json` (Thermal state and idempotency ledger).

### Terminal States
- `SUCCESS`: Batch processed fully, heat updated, input cleared.
- `DEDUPE_SKIP`: Sequence already in ledger, no side effects.
- `PARSE_ERROR`: DNA malformed, recorded in ledger/output, batch continues.
- `THERMAL_OVERLOAD`: `system_heat` >= `MAX_HEAT`, batch aborted, heat cost applied.
- `ATOMIC_FAILURE`: IO error during write, no files modified, input NOT cleared.

### Invariants
- `system_heat` is always persisted even on failure (if possible).
- `toSequence.txt` is only cleared if the entire batch process completes or gracefully handles errors.
- No partial writes to JSON/CSV (all-or-nothing per batch).

### Idempotency Key
- The `dna_sequence` string itself.

### Required Logs
- `JSON_LOG: { "step": "start", "correlation_id": "...", "dna_sequence": "..." }`
- `JSON_LOG: { "step": "complete", "outcome": "success", "latency_ms": 123 }`
- `JSON_LOG: { "step": "refusal", "reason": "thermal_overload", "heat": 10.5 }`
