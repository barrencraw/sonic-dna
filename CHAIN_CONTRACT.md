# Mini Chain Contract: DNA Batch Parsing

## Overview
**Chain Name:** `dna_batch_parser`
**Purpose:** Parses raw DNA sequence strings from `data/raw/toSequence.txt`, extracts sound properties using predefined JSON rulesets, appends structured outputs to `data/output/toSequence_parsed.json` and `.csv`, and records processing outcomes in `data/processed_ledger.json`.

---

## Contract Specification

### 1. Trigger
- Manual or scheduled execution via `main.py --once`.
- Event-driven background watcher loop in `main.py` detecting non-empty content in `data/raw/toSequence.txt`.

### 2. Inputs
- `input_file`: Path to `data/raw/toSequence.txt` containing newline-delimited DNA sequences.
- `correlation_id` (optional string): Trace identifier; generated via `uuid.uuid4()` if omitted.
- `actor_id` (optional string): Defaults to `'batch_parser'`.

### 3. Terminal States
- `success`: DNA sequence successfully matched against rules and parsed.
- `error`: DNA sequence failed rule parsing (recorded with error detail, status `'error'`).
- `skipped`: DNA sequence previously processed (deduplicated via ledger lookup).

### 4. Invariants
- **No Duplicate Side Effects:** Processing an identical DNA sequence multiple times must not create duplicate entries in output JSON or CSV files.
- **Output Alignment:** Every successfully written sequence or error entry in JSON must have a corresponding entry in CSV and `processed_ledger.json`.
- **Input Preservation on Failure:** `data/raw/toSequence.txt` is cleared ONLY when `run_batch()` completes without unhandled persistence or load exceptions.

### 5. Error Taxonomy
- `DNAProcessingError`: Base exception for all batch parsing issues.
- `RuleLoadError` (subclass of `DNAProcessingError`): Raised when JSON rules in `rules/` cannot be loaded.
- `PersistenceError` (subclass of `DNAProcessingError`): Raised when atomic tempfile write, fsync, or rename operations fail.
- `RuleParseError` (domain error): Raised per-sequence on rule mismatch; caught internally and recorded as terminal status `'error'`.

### 6. Idempotency Key
- **Key Strategy:** The raw DNA sequence string (e.g. `VOL08900750712`).
- **Ledger Path:** `data/processed_ledger.json`.
- **Deduplication Logic:** Before parsing, `dna_sequence` is checked against `processed_ledger.json`. If present, parsing is skipped (`dedupe_hit=True`).

### 7. Atomicity Boundary
- **Filesystem Write:** All JSON/CSV outputs and ledger state updates are prepared in memory, written to a temporary directory inside `data/output/`, flushed, and synced to disk via `fsync()`.
- **Commit Phase:** Atomic replacement (`os.replace`) ensures either all destination files update atomically or none do.
- **Queue Clearance:** Input file truncation in `main.py` occurs strictly after successful completion of `run_batch()`.

### 8. Required Telemetry Logs
All structured logs are emitted to standard output with prefix `JSON_LOG:` formatted as JSON objects containing:
- `timestamp`: UTC ISO 8601 timestamp.
- `correlation_id`: Trace UUID.
- `actor_id`: Component/actor name (`batch_parser`).
- `chain_name`: `"dna_batch_parser"`.
- `step`: Progress identifier (`"start"`, `"step"`, `"end"`).
- `outcome`: Terminal state or step status (`"started"`, `"success"`, `"error"`, `"skipped"`, `"completed"`).
- `latency_ms`: Duration in milliseconds.
- `idempotency_key`: DNA sequence string (for sequence-level step logs).
- `outcome_detail`: Context detail or error message.

---

## Telemetry Grep Recipes

1. **Extract all structured JSON logs for a batch execution:**
   ```bash
   grep "JSON_LOG:" app.log | sed 's/.*JSON_LOG: //' | jq .
   ```

2. **Filter by specific correlation ID:**
   ```bash
   grep "JSON_LOG:" app.log | grep "<correlation_id>" | sed 's/.*JSON_LOG: //' | jq .
   ```

3. **Track deduplicated idempotency hits:**
   ```bash
   grep "dedupe_hit=True" app.log
   ```

4. **Identify processing failures:**
   ```bash
   grep "JSON_LOG:" app.log | grep '"outcome":"error"'
   ```
