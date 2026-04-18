# Chain Contract: DNA Batch Parsing

## Trigger
- Manual execution of `main.py --once`
- Background file watcher in `main.py` detecting changes in `data/raw/toSequence.txt`.

## Inputs
- `data/raw/toSequence.txt`: A file containing DNA strings, one per line.
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Existing idempotency ledger.
- `data/output/toSequence_parsed.json`: Existing cumulative JSON output.
- `data/output/toSequence_parsed.csv`: Existing cumulative CSV output.

## Terminal States
- `SUCCESS`: All new DNA strings parsed and committed to outputs.
- `ERROR`: A critical failure occurred (e.g., IO error, rule load failure).
- `SKIPPED`: DNA string was already in the ledger.
- `NO_NEW_DNA`: Input file was empty or all strings were already processed.
- `PARTIAL_SUCCESS`: Some strings failed parsing but were recorded in the ledger as errors.

## Invariants
- No duplicate entries in `toSequence_parsed.json`/`.csv` for the same DNA string.
- The ledger, JSON, and CSV outputs must remain in sync (atomic commit).
- Input file `toSequence.txt` is only cleared upon successful batch processing.

## Error Classes
- `RuleLoadError`: Rules folder missing or malformed JSON rules.
- `RuleParseError`: DNA string does not match any rule.
- `PersistenceError`: Failed to write to temp files or atomic rename failed.
- `DNAProcessingError`: Generic base error for the chain.

## Idempotency Key
- The DNA string itself.

## Atomicity Boundary
- The "Atomic Write Pattern" in `utils/dna_ui.py`: Writing JSON, CSV, and Ledger to a temp directory, then using `os.replace` to commit all three.

## Required Logs (Structured)
- `timestamp` (ISO8601 UTC)
- `correlation_id` (UUID4)
- `chain_name`: "dna_batch_chain"
- `step`: "start", "process_dna", "commit", "end"
- `outcome`: `Outcome` Enum
- `idempotency_key`: DNA string
- `actor_id`: System user

## Grep Recipes
- `grep "dedupe_hit=True" dna_output.log` (Check idempotency hits)
- `grep "outcome=ERROR" dna_output.log` (Find failures)
- `grep "terminal_outcome=success" data/processed_ledger.json | wc -l` (Count successes)
