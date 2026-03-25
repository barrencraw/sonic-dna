# Chain Contract: DNA Batch Parsing

## Trigger
`utils.dna_ui.main()` called by `main.py` (Watcher or Once-Runner).

## Inputs
- `data/raw/toSequence.txt`: DNA strings (one per line).
- `rules/*.json`: Domain rule definitions.
- `data/processed_ledger.json`: Persistent idempotency ledger.

## Terminal States
- **SUCCESS**: All new DNA strings processed; JSON/CSV/Ledger updated atomically.
- **ERROR**: Infra failure (e.g., Disk Full); no state committed.
- **PARTIAL_SUCCESS**: All strings processed, some had `RuleParseError` (recorded as errors in artifacts); JSON/CSV/Ledger updated atomically.

## Invariants
- **Consistency**: Output JSON/CSV entries must correspond to entries in the Processed Ledger.
- **Atomicity**: Either JSON, CSV, AND Ledger are all updated, or none are.
- **Retention**: Input file `toSequence.txt` is only truncated by the caller (`main.py`) if the batch parser completes without an unhandled exception.

## Error Classes
- `RuleLoadError`: Rules cannot be loaded from `rules/`.
- `PersistenceError`: Writing to disk or atomic rename fails.
- `DNAProcessingError`: Generic processing failure.

## Idempotency Key
The DNA string itself (e.g., `VOL08900750712`).

## Atomicity Boundary
Unified "Temp File + Sync + Atomic Rename" block covering:
1. `data/output/toSequence_parsed.json`
2. `data/output/toSequence_parsed.csv`
3. `data/processed_ledger.json`

## Required Logs
- `[START] dna_batch_chain`
- `[Idempotency] key=... dedupe_hit=... terminal_outcome=...`
- `[STEP] processing_dna key=...`
- `[OK] Processed ... new DNA strings.`
- `[END] dna_batch_chain outcome=...`

---

## Telemetry Triage (Grep Recipe)
To view the execution trace of the batch processing chain:
```bash
grep -E "\[START\]|\[Idempotency\]|\[STEP\]|\[OK\]|\[END\]" output.log
```
