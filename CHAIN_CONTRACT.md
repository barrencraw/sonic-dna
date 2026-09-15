# Chain Contract: DNA Batch Parsing & Ledger Storage

## Overview
This contract governs the DNA Batch Parsing chain located in `main.py` and `utils/dna_ui.py`. The chain is responsible for ingesting raw DNA sequence lines, decoding them against modular JSON rule specifications, maintaining an append-only deduplicated processing ledger, and persisting structured outputs (JSON and CSV).

---

## 1. Trigger
- **Manual Batch Trigger:** Invoking `python main.py --once` or calling `utils.dna_ui.main()` directly.
- **Watcher Trigger:** Background thread in `main.py` detecting changes to `data/raw/toSequence.txt`.

---

## 2. Inputs
- `data/raw/toSequence.txt`: Text file containing 1 or more line-delimited DNA sequences (e.g. `VOL08900750712`).
- `rules/rules_*.json`: Declarative JSON schemas specifying encoding, variable names, ranges, and field boundaries.
- `data/processed_ledger.json`: Persistent ledger tracking previously processed idempotency keys and terminal outcomes.

---

## 3. Terminal States & Invariants
- **Terminal States:**
  - `success`: DNA sequence parsed successfully and accumulated in output buffers.
  - `error: <reason>`: DNA sequence failed rule parsing; error recorded without halting remaining batch sequences.
- **Invariants:**
  - **No Duplicate Processing:** DNA sequences existing in `data/processed_ledger.json` are skipped (dedupe hit).
  - **All-or-Nothing Side Effects:** Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`) are rewritten atomically using temporary directory flushes and atomic `os.replace`.
  - **Queue Retention on Failure:** If processing or persistence fails with an exception (`DNAProcessingError`), `data/raw/toSequence.txt` MUST NOT be cleared by `main.py`.

---

## 4. Error Taxonomy
- `DNAProcessingError`: Base exception for all batch parsing domain failures.
  - `RuleLoadError`: Raised when rules directory cannot be read or rules JSONs are invalid.
  - `PersistenceError`: Raised when atomic writing or file replacement of JSON, CSV, or ledger fails.
- `RuleParseError`: Raised by `DNACalculator` during string parsing (handled per-sequence, non-fatal to batch).

---

## 5. Idempotency Key & Deduplication Strategy
- **Idempotency Key:** `dna_sequence` (the raw DNA sequence string, e.g., `VOL08900750712`).
- **Ledger Entity:** Keyed in `data/processed_ledger.json`:
  ```json
  {
    "VOL08900750712": {
      "terminal_outcome": "success",
      "timestamp": "2025-06-02 12:00:00"
    }
  }
  ```

---

## 6. Atomicity Boundary
1. Sequence parsing occurs in memory.
2. Temporary directory created under `data/output/` (same filesystem).
3. Temporary JSON (`output.json`), CSV (`output.csv`), and Ledger (`ledger.json`) files written, flushed (`jf.flush()`), and synced (`os.fsync(jf.fileno())`).
4. Files atomically renamed via `os.replace` to final destination paths.
5. `toSequence.txt` cleared ONLY upon unhandled execution success.

---

## 7. Required Logs & Observability
- **Start Log:** `[Batch] Starting batch processing for input file: <path>`
- **Step Log:** `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- **End Log:** `[OK] Processed <count> new DNA strings. Total in ledger: <total>`

---

## 8. Grep Recipes
- **Find Idempotency Hits:** `grep "dedupe_hit=True" logs.txt`
- **Find Non-Idempotency Hits:** `grep "dedupe_hit=False" logs.txt`
- **Find Parsing Failures:** `grep "terminal_outcome=error" logs.txt`
- **Find Persistence Failures:** `grep "PersistenceError" logs.txt`
