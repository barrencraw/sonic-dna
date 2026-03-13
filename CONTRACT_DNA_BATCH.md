# DNA Batch Parsing Chain Contract

## 1. Triage / Defect Class
- **Chain:** DNA Batch Parsing (`utils/dna_ui.py`)
- **Defect Class:** Logic Error / Torn Writes / Atomicity
- **Win Condition:** DNA strings are processed exactly once, and all side effects (JSON output, CSV output, and Idempotency Ledger) are committed as a single atomic unit, with structured observability logs.

## 2. Contract Definition

### Trigger
- **Watcher Mode:** Triggered by `main.py` when change detected in `data/raw/toSequence.txt`.
- **Once-Runner Mode:** Triggered by `main.py --once`.

### Inputs
- `data/raw/toSequence.txt`: Text file containing one DNA string per line.
- `rules/*.json`: Domain rules for parsing DNA.
- `data/processed_ledger.json`: The idempotency ledger.

### Outputs
- `data/output/toSequence_parsed.json`: Cumulative JSON of all parsed DNA.
- `data/output/toSequence_parsed.csv`: Cumulative CSV of all parsed DNA.
- `data/processed_ledger.json`: Updated idempotency ledger.

### Terminal States
- `SUCCESS`: New DNA strings processed and committed.
- `NO_NEW_DATA`: Input file was empty or all strings were already in ledger.
- `ERROR`: A transient or permanent error occurred; no changes were committed.

### Invariants
1. **Atomicity:** JSON, CSV, and Ledger updates must be committed together. If one fails, none should be updated.
2. **Deduplication:** A DNA string already present in the ledger must NOT be re-added to JSON/CSV.
3. **Queue Drain:** The input file (`toSequence.txt`) must ONLY be truncated if all output persistence succeeds.
4. **Consistency:** Existing data in JSON/CSV/Ledger must be preserved (cumulative).

### Error Classes
- `RuleLoadError`: Rules folder missing or malformed.
- `RuleParseError`: Individual DNA string doesn't follow rules.
- `PersistenceError`: IO failure during atomic write or swap.

### Observability
All logs must be prefixed with `[OBSERVABILITY]` and include:
- `correlation_id` (UUID)
- `actor_id` (`system` for watcher, `user_batch` for once-runner)
- `step` (`start`, `process_dna`, `terminal`)
- `outcome` (`SUCCESS`, `ERROR`, `DEDUPE`, `NO_NEW_DATA`)
- `idempotency_key` (The DNA string)

## 3. Implementation Pattern
- **Stage:** Write Ledger, JSON, and CSV to a temporary directory on the same partition.
- **Commit:** Use `os.replace` to atomically swap all three files.
- **Cleanup:** Clear input file ONLY after successful commit.

## 4. Verification
- `tests/test_dna_batch_hardened.py`: Regression test for partial failures and idempotency.
- Grep recipe: `grep "\[OBSERVABILITY\]" output.log`
