# DNA Batch Parsing Chain Contract

## 1. Overview
The **DNA Batch Parsing Chain** is the core data processing path for SonicDNA. It transforms raw DNA strings into structured JSON/CSV data while ensuring idempotency and atomic persistence.

## 2. Chain Identification
- **Chain Name:** `dna_batch_chain`
- **Trigger:**
    - **Watcher:** Continuous monitoring of `data/raw/toSequence.txt`.
    - **Manual:** CLI invocation via `python3 main.py --once`.
- **Inputs:**
    - `data/raw/toSequence.txt`: A newline-delimited file of DNA strings.
- **Idempotency Key:** The DNA string itself (e.g., `VOL08900750712`).

## 3. Terminal States
- `SUCCESS`: All new DNA strings in the batch were processed and persisted correctly.
- `PARTIAL_FAILURE`: Some DNA strings failed parsing, but the system recorded the failure and proceeded.
- `ERROR`: An infrastructure or logic failure prevented the batch from being committed (e.g., `PersistenceError`).

## 4. Invariants
- **Idempotency:** Re-processing the same DNA string must not result in duplicate entries in JSON/CSV outputs or the ledger.
- **Atomicity:** All output updates (JSON, CSV, and `processed_ledger.json`) must commit together or not at all.
- **Queue Drainage:** `toSequence.txt` must only be cleared if the persistence of all outputs succeeds.

## 5. Observability (Log Contract)
All structured logs must be prefixed with `[OBSERVABILITY]` and include:
- `correlation_id`: A UUID linking all steps of a single batch run.
- `actor_id`: `watcher` or `once_runner`.
- `step`: `start`, `process_dna`, `commit`, `end`.
- `outcome`: `processing`, `success`, `error: <reason>`, `refusal`.
- `latency_ms`: Duration of the specific step or total run.
- `idempotency_key`: DNA string (for `process_dna` step).

### Telemetry Grep Recipe
```bash
grep -E "\[OBSERVABILITY\]|\[Idempotency\]"
```

## 6. Error Classes
- `RuleParseError`: DNA string violates domain invariants or rule schema.
- `RuleLoadError`: Missing or corrupt ruleset JSON.
- `PersistenceError`: Failure during atomic file commit (e.g., disk full, permission denied).
