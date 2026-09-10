# DNA Batch Parsing Chain Contract

## 1. Trigger
- Manual execution of `main.py --once`
- Background watcher loop in `main.py` detecting non-empty `data/raw/toSequence.txt`
- Direct program call to `utils.dna_ui.main()` or `run_batch()`

## 2. Inputs
- Input file: `data/raw/toSequence.txt` containing newline-separated DNA sequence strings (e.g., `VOL08900750712`)
- Rule JSON configurations: `rules/rules_*.json`

## 3. Terminal States
- `success`: DNA sequence successfully parsed according to matching rule and outputs updated
- `error`: DNA sequence invalid or rule parsing failed (`RuleParseError`); error recorded in outputs
- `skipped`: DNA sequence previously processed (deduplication hit via idempotency key)

## 4. Invariants
- **Idempotency**: Any DNA string present in `data/processed_ledger.json` will be skipped without re-parsing or creating duplicate output records.
- **Atomicity**: Output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) and `processed_ledger.json` are written atomically using temporary directory flushes and `os.replace`. If an IO error occurs during persistence, no output files are updated or corrupted.
- **Watcher Safety**: The watcher in `main.py` only truncates `data/raw/toSequence.txt` if `run_batch()` succeeds without raising an unhandled processing or persistence exception.

## 5. Error Taxonomy
- `DNAProcessingError`: Base exception for all processing failures
- `RuleLoadError`: Subclass raised when rule configurations cannot be loaded from `rules/`
- `PersistenceError`: Subclass raised when atomic writes or ledger saves fail
- `RuleParseError`: Internal exception raised by `DNACalculator` when a sequence fails schema parsing

## 6. Idempotency Key
- The raw DNA string (e.g. `VOL08900750712`) acts as the idempotency key in `data/processed_ledger.json`.

## 7. Atomicity Boundary
- Output directory: `data/output/`
- Atomic writes write JSON and CSV files to a temporary folder inside `data/output/`, call `flush()` and `os.fsync()`, and perform atomic `os.replace` to `toSequence_parsed.json` and `toSequence_parsed.csv`.

## 8. Required Logs & Telemetry
- `[Watcher] Started. Monitoring data/raw/toSequence.txt...`
- `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `[OK] Processed <N> new DNA strings. Total in ledger: <M>`
- `[Watcher][CRITICAL] DNA processing failed: <error>`

## 9. Grep Recipes
```bash
# Check deduplication hits
grep "dedupe_hit=True" logs.txt

# Check critical watcher failures
grep "\[Watcher\]\[CRITICAL\]" logs.txt

# Check completed batch summaries
grep "\[OK\] Processed" logs.txt
```
