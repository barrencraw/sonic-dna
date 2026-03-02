# SonicDNA Observability Guide

This document defines the structured logging contract for the SonicDNA system. All logs adhering to this contract are prefixed with `[OBSERVABILITY]`.

## Structured Log Keys

### Required Fields
- `correlation_id`: A unique ID (UUID v4) shared across all steps in a single processing chain.
- `chain_name`: The name of the process chain (e.g., `dna_batch_parser`).
- `version`: The version of the observability contract (e.g., `1.0.0`).
- `step`: The specific stage of the process (e.g., `start`, `read_input`, `process_dna`, `terminal`).
- `outcome`: The result of the step (`success`, `error`, `skipped`, `initiated`, `processing`).
- `latency_ms`: Total time elapsed since the start of the chain in milliseconds.
- `step_latency_ms`: Time elapsed during this specific step.
- `timestamp`: UTC timestamp of the log event.

### Context/Domain Fields
- `causal_event_id`: Identifies the event that triggered the chain (e.g., SHA256 hash of input file content).
- `session_id`: Identifies the user session or background process (e.g., `background-watcher`, `cli-user`).
- `trigger`: How the chain was started (`watcher`, `manual_once`).
- `idempotency_key`: The unique key used for deduplication (the DNA string).
- `dedupe_hit`: Boolean indicating if the item was already processed.

### Error Fields
- `error_message`: Human-readable error description.
- `error_classification`: Typed error class (e.g., `RuleLoadError`, `PersistenceError`).
- `error_cause`: The underlying exception or cause.

## Expected Sequence (DNA Batch Parser)

1. `start`: Chain initiated.
2. `load_rules`: Rules loaded from the `rules/` directory.
3. `read_input`: Input DNA strings read from `toSequence.txt`.
4. `load_ledger`: Idempotency ledger loaded.
5. `process_dna` (repeats): One log per DNA string.
   - `outcome=processing` if new.
   - `outcome=skipped` if `dedupe_hit=True`.
6. `atomic_persist`: Results written to disk.
7. `terminal`: Chain completed.

## Grepping Logs

To see all observability logs:
```bash
grep "\[OBSERVABILITY\]" output.log
```

To follow a specific chain:
```bash
grep "<correlation_id>" output.log
```

## Sample Redaction Rules
- DNA strings should be treated as data, but if they contain sensitive identifiers in the future, they should be hashed.
- `session_id` should not contain PII (Usernames are currently used in CLI mode; consider hashing if privacy is a concern).
