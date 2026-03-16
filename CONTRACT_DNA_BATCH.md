# DNA Batch Processing Contract

## Chain Name
`dna_batch_chain`

## Win Condition
Hardened DNA processing chain that is atomic, idempotent, and fully observable.
- Atomicity across all output files (JSON, CSV, Ledger).
- Idempotency per DNA string.
- Structured Observability.

## Trigger
- Modification of `data/raw/toSequence.txt` (Watcher).
- Execution of `main.py --once` (Once-Runner).

## Inputs
- DNA strings from `toSequence.txt`.
- Idempotency ledger (`data/processed_ledger.json`).
- Existing parsed data (JSON/CSV).

## Terminal States
- `SUCCESS`: DNA string processed correctly.
- `ERROR`: DNA string failed validation or parsing.
- `DEDUPE`: DNA string already present in the ledger.
- `NO_NEW_DATA`: No new DNA strings found in the input file.

## Invariants
- **Atomicity**: Ledger and output files must be updated as a single unit. If any write fails, none should be committed.
- **Idempotency**: Each unique DNA string must be processed exactly once per ledger state.
- **Data Integrity**: The input file (`toSequence.txt`) is only cleared if the entire batch processes and persists successfully.
- **Observability**: Every batch execution must emit a start, per-item step, and terminal log with the `[OBSERVABILITY]` prefix.

## Observability Fields
- `correlation_id`: Unique UUID for the batch execution.
- `actor_id`: `watcher` or `once_runner`.
- `step`: `start_batch`, `process_dna`, `commit_batch`.
- `outcome`: Terminal state for the step.
- `latency_ms`: Time taken for the step.
- `idempotency_key`: The DNA string itself.

## Grep Recipes
- `grep "\[OBSERVABILITY\]" output.log`
- `grep "outcome=ERROR" output.log`
