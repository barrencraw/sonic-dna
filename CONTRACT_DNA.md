# DNA Batch Parsing Contract

## Overview
This contract defines the behavior, invariants, and terminal states for the DNA Batch Parsing chain.

## Chain Contract
- **Trigger:** Addition of new non-empty lines to `data/raw/toSequence.txt`.
- **Inputs:**
  - `toSequence.txt`: Raw DNA strings (one per line).
  - `processed_ledger.json`: State of already processed DNA strings.
  - `rules/*.json`: Domain rules for parsing.
- **Terminal States:**
  - `SUCCESS`: New DNA processed; JSON, CSV, and Ledger updated atomically.
  - `ERROR`: Processing failed; no changes to output files or ledger; input file retained.
  - `DEDUPE`: No new DNA strings found or all input DNA strings already exist in the ledger.
- **Invariants:**
  - **Atomicity:** JSON, CSV, and Ledger updates must succeed together or fail together (Atomic Write + Commit).
  - **Idempotency:** A DNA string is never processed twice if its result is already in the ledger.
  - **Consistency:** JSON and CSV outputs must always reflect the same data as the ledger.
- **Observability:**
  - All executions emit structured JSON logs with the `[OBSERVABILITY]` prefix.
  - Logs include `correlation_id`, `chain_name`, `version`, `step`, and `latency_ms`.
  - Step transitions: `start` -> `parsing` -> `persisting` -> `terminal`.
- **Error Handling:**
  - `RuleParseError` for individual DNA strings is caught and recorded in the outputs as an "error" outcome, allowing the rest of the batch to continue.
  - `PersistenceError` or other critical failures abort the chain and do not clear the input file.
