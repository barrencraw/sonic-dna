# Contract: DNA Batch Chain

## 1. Trigger
- **Manual**: User appends DNA strings to `data/raw/toSequence.txt`.
- **Automated**: System watcher (`main.py`) detects file changes and triggers `run_batch`.

## 2. Inputs
- `data/raw/toSequence.txt`: One DNA sequence per line.
- `data/processed_ledger.json`: Persistence for idempotency and system state.

## 3. Terminal States
- `SUCCESS`: DNA string parsed and added to cumulative output.
- `ERROR`: Rule parse failure or persistence error.
- `SKIPPED`: Idempotency hit (already processed).
- `REFUSED`: Thermal overload lockout.

## 4. Invariants
- **Idempotency**: A single DNA string will never result in duplicate entries in `toSequence_parsed.json`.
- **Atomicity**: Output files and ledger are updated together or not at all.
- **Thermal Debt**: Every processed sequence adds 5.0 units of heat. System locks at 100.0.

## 5. Tradeoff: Thermal Debt (Fatigue Axis)
- **What the player wants**: Rapid batch processing of many DNA sequences.
- **What the world demands**: Hardware stability. The system is indifferent to your deadlines.
- **Consequence**:
    - **Choice A (Aggressive)**: Process large batches → Overheat → Hard lockout (cooldown required).
    - **Choice B (Conservative)**: Process small batches → System stays cool → Continuous but slower operation.
- **Skillful Play**: Pacing input to match the 0.5 units/sec cooling rate, ensuring the system never crosses the 100.0 threshold.

## 6. UI Message Keys (Indifferent Tone)
- `CONSEQUENCE_APPLIED`: "Thermal stress increased. Current heat: {heat}%."
- `REFUSAL_REASON`: "System state: Critical. Thermal overload detected. Processing refused."
- `NEXT_ACTION_HINT`: "Allow hardware to dissipate heat. Estimated cooldown: {seconds}s."

## 7. Logs (Observability)
- Standard prefix: `JSON_LOG: `
- Fields: `timestamp`, `correlation_id`, `step`, `outcome`, `system_heat`.
