# SonicDNA Idempotency Index

## Entry Points Analysis

| Trigger | “Same request” equivalence definition (candidate idempotency key) | Current dedupe (before hardening) | Duplication blast radius (double spend, duplicate event, torn state) |
| :--- | :--- | :--- | :--- |
| **Watcher (`main.py`)** | Full content of `toSequence.txt` | In-memory `last_content` check | Redundant parsing/overwriting of `toSequence_parsed.json` if file isn't cleared fast enough. |
| **Batch Parser (`utils/dna_ui.py`)** | DNA string (e.g., `VOL08900750712`) | None (overwrote output every time) | Duplicate entries in cumulative datasets; wasted CPU/IO on already-calculated DNA. |
| **UI "Download" Button** | Selected wave + timestamp | None (OS handles overwrite) | Redundant file writes to disk. |
| **UI "Play" Button** | Selected wave | `is_playing` flag | Minimal; `sd.stop()` handles overlaps. |

---

## Selected Critical Chain: DNA Batch Parser & Ledger

The **DNA Batch Parser** was selected because it is the core data processing path. Without idempotency, duplicated DNA strings (due to retries or at-least-once message delivery) would lead to redundant computation and corrupted/duplicate entries in the cumulative output files (`toSequence_parsed.json`/`.csv`).

### Implementation Details:
- **Best Available Primitive:** Processed message ledger (`data/ledger.json`).
- **Idempotency Key:** The DNA string itself (unique representation of the sound property).
- **Observability:** Logs `idempotency_key`, `dedupe_hit`, and `terminal_outcome`.
- **Side Effects:** Results are appended to cumulative JSON/CSV stores only if the key is new in the ledger.

### Verification (Proof):
Run the adversarial double-invocation test:
```bash
PYTHONPATH=. python3 tests/test_idempotency.py
```
This test proves:
1. **Adversarial double invocation:** Same key → no duplicate side effects in output files.
2. **Retry after failure:** System recovers and maintains consistency without corruption.
