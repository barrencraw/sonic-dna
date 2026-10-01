# Chain Contract: DNA Batch Parsing

## Overview
This mini chain contract defines the specification, invariants, and failure modes for the DNA Batch Parser (`utils/dna_ui.py` and `main.py`).

## Contract Specifications

| Property | Definition |
| :--- | :--- |
| **Trigger** | Batch processing request via watcher loop (`main.py`) or `--once` CLI argument. |
| **Inputs** | Raw DNA sequence strings read line-by-line from `data/raw/toSequence.txt`. |
| **Terminal States** | <ul><li>`success`: DNA sequence parsed correctly and appended to output dataset & ledger.</li><li>`error`: DNA sequence failed rule parsing, recorded with error detail in output dataset & ledger.</li><li>`skipped`: DNA sequence already present in `data/processed_ledger.json` (deduplicated hit).</li></ul> |
| **Invariants** | 1. No partial/torn file writes (atomic replace of `.json` and `.csv`).<br>2. Deduplication hit prevents duplicate entries in JSON/CSV datasets.<br>3. `data/raw/toSequence.txt` is cleared ONLY when batch parser completes without unhandled exceptions. |
| **Error Classes** | <ul><li>`DNAProcessingError`: Base exception class.</li><li>`RuleLoadError`: Raised when JSON rule files cannot be loaded.</li><li>`PersistenceError`: Raised when I/O or atomic rename fails.</li><li>`RuleParseError`: Raised when a DNA string violates rule schemas.</li></ul> |
| **Idempotency Key** | The raw DNA sequence string (e.g., `VOL08900750712`). |
| **Atomicity Boundary** | All batch results are written to temporary staging files on the target filesystem with `flush()` and `fsync()` before being atomically renamed (`os.replace`) into `data/output/`. |

---

## Required Log Telemetry

Each execution of the batch parser emits structured telemetry logs:
- **Start Log:** `[Batch Parser] Starting execution...`
- **Idempotency Step Log (Dedupe Hit):** `[Idempotency] key=<KEY> dedupe_hit=True terminal_outcome=<OUTCOME>`
- **Idempotency Step Log (New Entry):** `[Idempotency] key=<KEY> dedupe_hit=False terminal_outcome=<OUTCOME>`
- **Completion End Log:** `[Batch Parser] Complete. Processed <COUNT> new DNA strings. Total in ledger: <TOTAL>`

---

## Grep Recipes

To audit idempotency and execution status in log outputs:

```bash
# Filter all idempotency checks
grep "\[Idempotency\]" app.log

# Filter deduplication hits
grep "dedupe_hit=True" app.log

# Track start and completion boundaries
grep "\[Batch Parser\]" app.log
```
