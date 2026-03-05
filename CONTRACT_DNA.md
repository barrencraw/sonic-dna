# DNA Batch Parsing Contract

## Win Condition
DNA processing reliably appends to outputs and updates the ledger as a single atomic unit, handles errors without leaving torn state, and avoids re-processing.

## Done When
- `utils/dna_ui.py` implements a unified **Atomic Write + Commit** pattern for JSON, CSV, and the processed ledger.
- The processing loop correctly handles idempotency and records terminal states (`SUCCESS`, `ERROR`, `DEDUPE`) for every input DNA string.
- The system emits structured logs via `utils/observability.py` including `correlation_id`, `outcome`, and `latency_ms`.
- The input file `data/raw/toSequence.txt` is cleared ONLY if the entire processing and persistence transaction succeeds.
- Regression guards in `test_atomicity.py` and `tests/test_idempotency.py` pass.

## Contract Details
- **Trigger:** `main.py` watcher or `--once` flag.
- **Inputs:** `data/raw/toSequence.txt` (one DNA string per line).
- **Outputs:**
    - `data/output/toSequence_parsed.json` (Cumulative)
    - `data/output/toSequence_parsed.csv` (Cumulative)
    - `data/processed_ledger.json` (Idempotency Ledger)
- **Idempotency Key:** The DNA string itself.
- **Atomicity Boundary:** All three output/ledger files must be updated together or not at all.
- **Error Classes:** `RuleParseError` (domain), `PersistenceError` (infra), `DNAProcessingError` (base).

## Grep Recipe
To monitor the DNA batch parsing chain:
```bash
tail -f logs/app.log | grep "\[OBSERVABILITY\]" | grep "dna_batch_parsing"
```
To find failed persistence steps:
```bash
grep "persistence" logs/app.log | grep "error"
```
