# Chain Contract: DNA Batch Parsing with Thermal Fatigue Protection

## 1. Trigger
- Triggered by the background file watcher or direct CLI `--once` execution processing `data/raw/toSequence.txt`.

## 2. Inputs
- A list of raw DNA sequence strings.

## 3. Terminal States
The system utilizes lowercase `DNAStatus` string enum values for terminal outcomes:
- `success`: DNA sequence successfully parsed and written to output formats.
- `error`: Invalid DNA sequence format or parsing error.
- `skipped`: DNA sequence bypassed due to pre-existing terminal outcome in the processed ledger.
- `refused`: Process refused due to thermal lockout safety threshold being exceeded.

## 4. Invariants
- **Heat Accumulation:** Every successfully parsed sequence adds `2.0` heat units.
- **Heat Decay:** The mainframe cools down at a rate of `0.5` heat units per second since the last processed timestamp.
- **Lockout Threshold:** If core heat exceeds the threshold of `10.0` heat units, further processing is refused, and a `ThermalOverloadError` is raised.
- **Next Action Hint:** Systemic feedback for failures/refusal must utilize an indifferent, informative, non-comforting tone:
  - Feedback Keys: `"Heat Accumulation"`, `"Thermal Lockout"`, `"Wait for dissipation. The system is indifferent to your deadlines."`.

## 5. Error Taxonomy
- `DNAProcessingError` (Base exception)
  - `InputReadError`: Failure reading input file.
  - `ThermalOverloadError`: Refused execution due to core heat lockout.
- `PersistenceError` (Base exception)
  - `LedgerLoadError`: Processed ledger file exists but is corrupted/contains invalid JSON.
  - `LedgerSaveError`: Failure writing ledger back to physical storage.
  - `AtomicWriteError`: Failure writing output formats atomically using the temporary folder rename pattern.

## 6. Idempotency Key
- Unique representation is the DNA sequence string itself.
- Skip any DNA sequence with terminal outcomes of `success` or `error` in the ledger.

## 7. Atomicity Boundary
- Either all processed sequences, system state, and ledger entries are physically committed to storage, or none are (retaining original state).
- Inputs are cleared from `toSequence.txt` only if processing completes successfully (no silent drains for `ThermalOverloadError`).

## 8. Required Logs & Grep Recipes
- Structured UTC JSON logs prefixed with `JSON_LOG:` emitting fields:
  - `timestamp` (UTC ISO 8601), `correlation_id`, `actor_id`, `chain_name`, `step`, `outcome`, `latency_ms`, `idempotency_key`, `outcome_detail`.
- Grep Recipe:
  `grep -rn "JSON_LOG:" .`
