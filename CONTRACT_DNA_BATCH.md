# DNA Batch Parsing Chain Contract

## Overview
Hardened batch processing for DNA strings with idempotency, atomic writes, and structured observability.

## Chain Details
- **Trigger:** Background watcher or `--once` flag in `main.py`.
- **Inputs:** `data/raw/toSequence.txt` (one DNA string per line).
- **Idempotency Key:** The DNA string itself.
- **Deduplication Logic:** Check `data/processed_ledger.json`. If key exists, skip processing.
- **Terminal States:** `SUCCESS`, `ERROR: <msg>`, `DEDUPE`.
- **Atomicity Boundary:** Updates to JSON, CSV, and Ledger files are committed together via temp-file rename.
- **Invariants:**
    - Input file is only cleared if the batch commit succeeds.
    - Output files remain consistent even if a crash occurs during I/O.
- **Error Classes:** `RuleParseError`, `PersistenceError`, `RuleLoadError`.

## Telemetry / Observability
- **Required Logs:**
    - `[OBSERVABILITY] step=batch_start dna_count=<n> correlation_id=<uuid>`
    - `[OBSERVABILITY] step=process_dna idempotency_key=<dna> outcome=<status> correlation_id=<uuid> dedupe_hit=<bool>`
    - `[OBSERVABILITY] step=batch_end outcome=SUCCESS new_processed=<n> latency_ms=<ms> correlation_id=<uuid>`
- **Grep Recipe:**
    - `grep -E "\[OBSERVABILITY\]|\[Idempotency\]"`
