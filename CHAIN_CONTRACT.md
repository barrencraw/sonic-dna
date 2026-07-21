# CHAIN CONTRACT: DNA Batch Parsing

## Overview
This document specifies the formal execution contract for the **DNA Batch Parsing** chain. It defines inputs, triggers, terminal states, error modes, invariants, and atomic boundaries to guarantee system stability and telemetry accuracy.

---

## 1. Chain Definition & Trigger
- **Trigger:** Appending new DNA sequence lines to the input queue file `data/raw/toSequence.txt`.
- **Actors/Orchestrators:**
  - Background Watcher Loop (`main.py`)
  - CLI Once-Runner (`main.py --once`)

---

## 2. Inputs & Data Structures
- **Input File:** `data/raw/toSequence.txt`
  - Format: One DNA sequence string per non-empty line (whitespace stripped).
- **Idempotency Ledger:** `data/processed_ledger.json`
  - Structure: A JSON dictionary mapping unique DNA sequence strings to processing metadata:
    ```json
    {
      "VOL08900750712": {
        "terminal_outcome": "success",
        "timestamp": "2025-06-03 12:00:00"
      }
    }
    ```
- **Idempotency Key:** The DNA sequence string itself (e.g., `"VOL08900750712"`).

---

## 3. Invariants
- **Deduplication:** Any DNA string already residing in the ledger with a terminal outcome (`success`, `error: ...`) MUST be skipped. It should never be parsed again or cause heat accumulation or redundant disk writes.
- **Atomic Commits:**
  - File modifications must follow an "all-or-nothing" execution. No partial/torn writes of output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) or the ledger file (`processed_ledger.json`) are permitted.
  - If processing a batch fails midway, output files and ledger MUST remain unaltered in their last valid state.
  - The input queue file `toSequence.txt` MUST NOT be cleared if any batch processing error or writing failure occurs.

---

## 4. Terminal States & Outcomes
Each individual DNA sequence results in one of the following terminal states:
1. **`success`:** The DNA string was successfully parsed by `DNACalculator`, and its variables are appended to output stores.
2. **`error: <detail>`:** The DNA string was malformed, failed validation rules, or threw a `RuleParseError`. This is recorded in the outputs and ledger as a terminal error.

---

## 5. Errors & Exceptions
- **`RuleLoadError`:** Raised when rules folder or rules JSON files cannot be loaded.
- **`RuleParseError`:** Raised when parsing a single DNA sequence fails (captured at item-level, recorded as terminal state `error`).
- **`PersistenceError`:** Raised when writing JSON/CSV output files atomically or saving the ledger file fails (aborting file system updates).
- **`DNAProcessingError`:** Base class for all critical failures in the chain.

---

## 6. Atomic Boundaries
1. **Output Writes (JSON + CSV):** Written atomically via temporary file generation in the output directory, flushing, physical sync (`os.fsync`), and atomic file replacement (`os.replace`).
2. **Ledger Writes (JSON):** Written atomically via temporary file generation, flushing, physical sync (`os.fsync`), and atomic file replacement (`os.replace`) to prevent corrupted/truncated ledger states (Torn Writes).

---

## 7. Required Telemetry Logs
Every batch run or sequence assessment must log structured traces containing:
- `idempotency_key` (DNA string)
- `dedupe_hit` (`True` if already in ledger, `False` if not)
- `terminal_outcome` (`success`, `error: <detail>`, or `processing`)
- UTC timestamps
- Standard step summaries (start, parsed counts, processed counts, output destinations)

---

## 8. Telemetry Grep Recipes
You can extract and monitor the system execution state and idempotency checks using the following commands:

### Grep Idempotency and Deduplication Events
```bash
# Extract all idempotency checks, deduplication hits, and processing outcomes
grep "\[Idempotency\]" stdout.log
```

### Grep Successful Parsed Outcomes
```bash
# Filter only successful parses
grep "terminal_outcome=success" stdout.log
```

### Grep Skipped/Deduplicated Entries
```bash
# Filter only skipped/deduplicated DNA strings
grep "dedupe_hit=True" stdout.log
```

### Grep Batch Completion Logs
```bash
# Filter batch parsing overview summaries
grep -E "\[OK\] Parsed|\[OK\] Processed" stdout.log
```
