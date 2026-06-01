# DNA Batch Processing Contract

## Chain Definition: DNA Batch Parsing
**Trigger:** Detected changes in `data/raw/toSequence.txt` by the watcher or manual execution via `--once`.

**Inputs:**
- DNA strings (one per line) in `data/raw/toSequence.txt`.
- `data/processed_ledger.json` (idempotency state).
- `data/system_state.json` (thermal fatigue state).

**Terminal States:**
- `SUCCESS`: Sequence parsed and committed to outputs.
- `PARSE_ERROR`: Sequence failed rule parsing; recorded as error in outputs.
- `SKIPPED`: Sequence already in ledger; no re-processing.
- `THERMAL_OVERLOAD`: Processing halted due to heat > 10.0.

**Invariants:**
- Every successfully processed DNA string MUST exist in the ledger.
- JSON and CSV outputs MUST stay in sync.
- `system_heat` MUST NOT exceed 10.0 without a `ThermalOverloadError`.
- `data/raw/toSequence.txt` MUST NOT be cleared if processing fails (atomicity).

**Error Classes:**
- `RuleLoadError`: Rules folder missing or corrupted.
- `RuleParseError`: DNA string doesn't match rules (non-fatal for batch).
- `PersistenceError`: File I/O failure or atomic rename failure.
- `ThermalOverloadError`: Hardware safety refusal.

**Idempotency Key:**
- The raw DNA string itself.

**Atomicity Boundary:**
- Multi-file commit (JSON, CSV, Ledger, System State) using temporary directory + atomic renames.
- The input file is cleared by `main.py` ONLY if the entire batch operation succeeds.

**Required Logs (Structured):**
- Fields: `timestamp`, `correlation_id`, `chain_name`, `step`, `outcome`, `actor_id`.
- Start/Step/End markers.
- Idempotency dedupe hits.

**Grep Recipe:**
```bash
grep -E "key=|dedupe_hit=|terminal_outcome=|JSON_LOG:"
```
