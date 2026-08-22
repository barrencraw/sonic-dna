# Chain Contract: DNA Batch Parsing

## Trigger
Watcher loop in `main.py` detecting non-empty `data/raw/toSequence.txt` or `--once` command-line execution.

## Inputs
- `data/raw/toSequence.txt`: Contains line-separated DNA sequences.

## Outputs
- `data/output/toSequence_parsed.json`: Cumulative array of parsed DNA records containing both legacy (`dna`) and canonical (`dna_sequence`) keys.
- `data/output/toSequence_parsed.csv`: Cumulative CSV table containing flattened parsed properties.
- `data/processed_ledger.json`: Structured processed ledger dictionary containing `ledger` entries and `system_state`.

## Terminal States
- `success`: DNA sequence parsed successfully against JSON ruleset.
- `error`: Rule parse error encountered for DNA sequence.
- `skipped`: DNA sequence previously processed (idempotency hit).
- `refused`: Sequence refused due to Thermal Lockout threshold (> 10.0 heat units).

## Invariants
1. Heat Accumulation: +2.0 heat units per newly processed DNA sequence.
2. Heat Decay: Cooling rate of 0.5 heat units per second.
3. Lockout Threshold: Core heat >= 10.0 heat units triggers `ThermalOverloadError`.
4. Atomicity: Output JSON and CSV files are updated atomically via temporary directory sync and rename.
5. Idempotency: Duplicate DNA sequences incur zero additional core heat and zero file I/O operations.
6. No Silent Drains: Input file `toSequence.txt` is cleared ONLY if batch execution succeeds without throwing `DNAProcessingError`.

## Error Taxonomy
- `DNAProcessingError` (Base class)
  - `InputReadError`
  - `RuleLoadError`
  - `PersistenceError`
    - `LedgerSaveError`
    - `LedgerLoadError`
    - `AtomicWriteError`
  - `ThermalOverloadError`

## UI Message Keys
- Consequence applied: `"Heat Accumulation"`
- Refusal reason: `"Thermal Lockout"`
- Next action hint: `"Wait for dissipation. The system is indifferent to your deadlines."`

## Required Logs & Grep Recipes
- Structured log prefix: `JSON_LOG:`
- Mandatory fields: `timestamp`, `correlation_id`, `actor_id`, `chain_name`, `step`, `outcome`, `latency_ms`, `idempotency_key`, `outcome_detail`.
- Grep recipe: `grep "JSON_LOG:" app.log`
