# DNA Batch Parsing Chain Contract

## 1. Overview
The DNA Batch Parsing chain is the core data processing path of SonicDNA. It transforms raw DNA strings into structured JSON and CSV datasets while maintaining atomicity and idempotency.

## 2. Chain Definition
- **Trigger:** `main.py` (Watcher loop or CLI `--once` flag) calls `utils.dna_ui.main()`.
- **Inputs:**
  - `data/raw/toSequence.txt`: Queue of DNA strings (one per line).
  - `rules/*.json`: Domain rules for parsing.
  - `data/processed_ledger.json`: Idempotency ledger.
- **Outputs:**
  - `data/output/toSequence_parsed.json`: Cumulative JSON results.
  - `data/output/toSequence_parsed.csv`: Cumulative CSV results.
  - `data/processed_ledger.json`: Updated ledger.

## 3. Terminal States
| State | Description |
| :--- | :--- |
| `SUCCESS` | DNA successfully parsed and results recorded. |
| `ERROR` | Parsing failed due to schema violation or logic error. |
| `SKIPPED` | DNA already exists in ledger (idempotency hit). |
| `REFUSED` | System in thermal lockout (not yet implemented in logic but reserved). |

## 4. Invariants
- **No Silent Drains:** `toSequence.txt` is only truncated if the batch processing succeeds.
- **Atomic Commit:** Ledger and output files (JSON, CSV) must be updated in a single atomic transaction (temp files + rename).
- **Idempotency:** Re-processing the same DNA string results in no additional side effects.

## 5. Error Classes
- `RuleLoadError`: Rules folder missing or corrupted.
- `RuleParseError`: DNA string does not match any registered rule.
- `PersistenceError`: IO failure during the atomic commit phase.

## 6. Telemetry Requirements
All lifecycle events must be logged with the prefix `JSON_LOG: ` followed by a JSON object containing:
- `timestamp`: ISO 8601.
- `correlation_id`: Trace ID from trigger.
- `chain_name`: `dna_batch_parsing`.
- `step`: `start`, `parsing_item`, `commit_phase`, `end`.
- `outcome`: Terminal state or `in_progress`.
- `idempotency_key`: DNA string (for `parsing_item` step).
- `latency_ms`: Duration of the step.

## 7. Analysis (Grep Recipe)
To analyze batch outcomes:
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //' | jq '.'
```
