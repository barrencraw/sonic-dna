# Chain Contract: DNA Batch Parsing

## Goal
Harden the DNA batch parsing process against partial failures and redundant processing while improving observability.

## Win Condition
The DNA Batch Parsing chain correctly parses DNA strings, maintains an idempotency ledger, and commits all changes (JSON, CSV, Ledger) atomically with standardized observability.

## Done When
- [ ] `utils/dna_ui.py` uses a unified atomic commit for JSON, CSV, and Ledger.
- [ ] `toSequence.txt` is only cleared if the entire batch commit succeeds.
- [ ] Logs include `correlation_id`, `actor_id`, and clear idempotency hits/misses.
- [ ] Indentation and logic errors in `utils/dna_ui.py` are fixed.
- [ ] Regression tests (`test_idempotency.py`, `test_atomicity.py`) pass.

## Contract
- **Trigger**: New lines in `data/raw/toSequence.txt`.
- **Inputs**: DNA strings (e.g., `VOL08900750712`).
- **Terminal States**:
    - `SUCCESS`: All new DNA processed, outputs and ledger updated, input cleared.
    - `ERROR`: Fatal error (e.g., disk full, rules missing); no changes committed.
- **Invariants**:
    - All three output files (JSON, CSV, Ledger) are updated as a single atomic transaction.
    - No DNA string is processed twice if it exists in the ledger.
- **Idempotency Key**: The DNA string itself.
- **Atomicity Boundary**: The `os.replace()` block in `utils/dna_ui.py`.
- **Observability**:
    - `[START] batch_id=<uuid>`
    - `[Idempotency] key=<dna> hit=<bool>`
    - `[OK] processed=<count> total_ledger=<count>`
