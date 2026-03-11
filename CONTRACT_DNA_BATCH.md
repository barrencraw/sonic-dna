# DNA Batch Processing Contract

## Overview
The DNA Batch Processing chain is responsible for reading DNA strings from a raw input file, parsing them into structured data using modular rules, and persisting the results in multiple formats (JSON and CSV) while maintaining an idempotency ledger.

## Contract
- **Trigger**: New non-empty content in `data/raw/toSequence.txt` (detected by watcher or manual invocation).
- **Inputs**:
    - `data/raw/toSequence.txt`: A text file with one DNA string per line.
    - `rules/*.json`: Modular rule definitions.
- **Terminal States**:
    - `SUCCESS`: All new DNA strings processed and persisted.
    - `NO_NEW_DATA`: No new DNA strings found after deduplication.
    - `ERROR`: A critical failure occurred (e.g., rule load error, persistence failure).
- **Invariants**:
    - Each unique DNA string is processed at most once per its lifetime in the ledger.
    - JSON, CSV, and the Ledger are updated atomically; they either all succeed or all remain in their previous state.
- **Error Classes**:
    - `RuleLoadError`: Failed to load or parse rule JSONs.
    - `DNAProcessingError`: General error during reading or processing DNA strings.
    - `PersistenceError`: Atomic write and rename failed.
- **Idempotency Key**: The raw DNA string itself.
- **Atomicity Boundary**: The update of `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json`.
- **Required Logs**:
    - `[OBSERVABILITY]` prefixed JSON logs for: `start`, `process_dna` (per string), `persistence`, and `complete`.
    - Logs must include `correlation_id`, `actor_id`, `chain_name`, `step`, and `timestamp` (ISO8601 UTC).

## Telemetry Triage (Grep Recipes)
- **View all processing events**:
  `grep "\[OBSERVABILITY\]" output.log`
- **Filter by a specific correlation ID**:
  `grep "test-corr-id" output.log | grep "\[OBSERVABILITY\]"`
- **Identify errors**:
  `grep '"outcome": "ERROR"' output.log | grep "\[OBSERVABILITY\]"`
- **Check latency of DNA parsing**:
  `grep "process_dna" output.log | grep "\[OBSERVABILITY\]" | sed -n 's/.*"latency_ms": \([0-9]*\).*/\1/p'`
