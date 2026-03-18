# DNA Batch Parsing Contract

## Win Condition
DNA Batch Parsing is atomic (ledger + data commit together) and observable (structured logs with correlation IDs).

## Definition
- **Trigger:** `main.py` (Watcher or Once-Runner) or direct invocation of `utils/dna_ui.py`.
- **Inputs:** `data/raw/toSequence.txt` (DNA strings, one per line).
- **Outputs:**
    - `data/output/toSequence_parsed.json` (Cumulative JSON)
    - `data/output/toSequence_parsed.csv` (Cumulative CSV)
    - `data/processed_ledger.json` (Idempotency Ledger)

## Terminal States
- `SUCCESS`: DNA string parsed and added to outputs.
- `ERROR`: Parsing failed (recorded in outputs and ledger).
- `DEDUPE`: DNA string already in ledger, skipped.
- `NO_NEW_DATA`: Batch executed but no new DNA found.

## Invariants (Safety & Correctness)
1. **Atomicity:** The update to the JSON output, CSV output, and Processed Ledger must be a single atomic transaction. Partial updates (e.g., JSON updated but Ledger not) are forbidden.
2. **Idempotency:** Re-running the same DNA string must result in a `DEDUPE` outcome with no additional side effects in the output files.
3. **Durability:** The input file (`toSequence.txt`) must only be cleared if the atomic commit of all outputs succeeds.
4. **Context Propagation:** All logs must carry a `correlation_id` and `actor_id`.

## Required Logs (Observability Contract)
All structured logs must use the `[OBSERVABILITY]` prefix and include:
- `correlation_id`: Unique UUID for the batch execution.
- `actor_id`: `watcher` or `once_runner`.
- `step`: Current stage (e.g., `batch_start`, `process_dna`, `batch_end`).
- `outcome`: Terminal state for the string or batch.
- `latency_ms`: Time taken to process an individual DNA string.
- `idempotency_key`: The DNA string itself.

## Grep Recipe for Telemetry Triage
`grep -E "\[OBSERVABILITY\]|\[Idempotency\]"`
