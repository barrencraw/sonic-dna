# Chain Contract: DNA Batch Parsing Chain

## Trigger
Batch trigger via `main.py` (`process_once` or `watch_loop`), GUI trigger, or programmatic call to `run_batch(correlation_id=..., actor_id=...)`.

## Inputs
- File input: `data/raw/toSequence.txt` containing line-delimited DNA sequences.
- Execution context parameters: `correlation_id` (string UUID), `actor_id` (string, e.g., `'batch_parser'`).

## Terminal States (`DNAStatus`)
- `success`: DNA sequence successfully parsed and added to output dataset.
- `error`: DNA sequence failed rule validation (`RuleParseError`). Output contains error record.
- `skipped`: DNA sequence previously processed and skipped due to idempotency hit.
- `refused`: Execution refused due to thermal overload lockout threshold.

## Invariants
1. **Atomicity**: Output JSON/CSV files and processed ledger are committed atomically. Partial/torn writes are impossible.
2. **Conditional Disk Writes**: Output JSON and CSV files are rewritten ONLY if `new_processed_count > 0`.
3. **Queue Draining**: The input file (`toSequence.txt`) is cleared ONLY if batch execution finishes without unhandled exceptions or thermal overload refusal.
4. **Thermal Balance**: Each processed sequence adds 2.0 heat units. Heat dissipates at 0.5 heat units per second. Threshold limit is 10.0 heat units.
5. **UI Messaging**: Thermal overload messages utilize key system descriptors:
   - Consequence: `"Heat Accumulation"`
   - Reason: `"Thermal Lockout"`
   - Next Action: `"Wait for dissipation. The system is indifferent to your deadlines."`
6. **Data Compatibility**: Both `dna` and `dna_sequence` fields are preserved in parsed JSON/CSV dictionaries to guarantee full backward compatibility.

## Error Taxonomy
- `DNAProcessingError` (base class for all batch processing errors)
  - `RuleLoadError` (raised when rule JSON files cannot be loaded)
  - `InputReadError` (raised when reading input files fails)
  - `PersistenceError` (base class for I/O persistence failures)
    - `LedgerLoadError` (raised when loading or parsing the ledger fails)
    - `LedgerSaveError` (raised when saving the ledger fails)
    - `AtomicWriteError` (raised when staging, syncing, or replacing output files fails)
  - `ThermalOverloadError` (raised when core heat >= 10.0 heat units)

## Idempotency Key Strategy
- **Idempotency Key**: The raw DNA sequence string.
- **Terminal Outcomes**: Lowercase string enum `DNAStatus` values (`"success"`, `"error"`, `"skipped"`, `"refused"`).
- **Deduplication**: Sequences matching existing terminal outcomes in the ledger are skipped prior to rule evaluation or heat accumulation.

## Atomicity Boundary
- Staging directory created within output directory (`data/output/`).
- Staged output files flushed (`jf.flush()`) and synced (`os.fsync(jf.fileno())`) prior to replace.
- Final commit executed via atomic `os.replace()`.

## Required Telemetry
Structured logs emitted with `JSON_LOG:` prefix:
- Mandatory fields:
  - `timestamp`: UTC ISO 8601 string (`YYYY-MM-DDTHH:MM:SSZ`)
  - `correlation_id`: Trace UUID string
  - `actor_id`: Component or caller identifier
  - `chain_name`: `"dna_batch_parsing"`
  - `step`: Current processing step (`start`, `parse`, `thermal_check`, `atomic_write`, `end`)
  - `outcome`: Lowercase status string
  - `latency_ms`: Step duration in milliseconds
  - `idempotency_key`: Raw DNA sequence string or batch summary ID
  - `outcome_detail`: Detailed message or error string

## Grep Recipes
- View all telemetry logs:
  `grep "JSON_LOG:" app.log`
- View non-success outcomes:
  `grep "JSON_LOG:" app.log | grep -E '"outcome":\s*"(error|refused)"'`
- View thermal fatigue overload events:
  `grep "JSON_LOG:" app.log | grep "ThermalOverloadError"`
