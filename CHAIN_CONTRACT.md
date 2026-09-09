# DNA Batch Parsing Chain Contract

## 1. Overview
The DNA Batch Parsing chain is responsible for reading raw SonicDNA sequence strings from disk, calculating/parsing their constituent sub-variable values via `DNACalculator`, and atomically persisting results to output datasets (`toSequence_parsed.json`, `toSequence_parsed.csv`) and an idempotency ledger (`processed_ledger.json`).

## 2. Trigger
- **Watcher process (`main.py`)**: Automatic background detection of non-empty content in `data/raw/toSequence.txt`.
- **CLI Batch (`main.py --once`)**: One-time manual execution.
- **Direct UI/Module Call**: Direct execution of `utils.dna_ui.main()`.

## 3. Inputs
- `data/raw/toSequence.txt`: Text file containing newline-separated DNA sequence strings.
- `rules/rules_*.json`: Rule definition files for rule-based parsing.
- `data/processed_ledger.json`: Historical ledger of processed DNA idempotency keys and terminal states.

## 4. Terminal States
- `SUCCESS`: All new DNA strings parsed and committed to output files and ledger.
- `SKIPPED`: Input DNA string already exists in `processed_ledger.json` (deduplicated).
- `ERROR`: Rule parsing error encountered (`RuleParseError`) recorded in output files and ledger as terminal error outcome.
- `CRITICAL_FAILURE`: System-level error (e.g., IO/Persistence error) preventing atomic write; raw input file retained for retry.

## 5. Invariants
1. **Deduplication / Idempotency**: A given DNA sequence string will never produce duplicate entries in `toSequence_parsed.json` or `toSequence_parsed.csv`.
2. **All-or-Nothing Output Atomicity**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are written atomically using temporary directory flushes and `os.replace`. Partial/torn writes are impossible.
3. **Input File Safety**: `toSequence.txt` is cleared if and only if `run_batch()` completes without unhandled exceptions.

## 6. Error Taxonomy
- `DNAProcessingError`: Base class for batch parsing errors.
- `RuleLoadError`: Subclass raised when rule definitions fail to load.
- `PersistenceError`: Subclass raised when atomic writing or ledger persistence fails.
- `RuleParseError`: Raised when a specific DNA string fails rule validation.

## 7. Idempotency Strategy
- **Key Definition**: The raw DNA string itself (e.g., `VOL08900750712`).
- **Storage**: `data/processed_ledger.json` storing key to `{ "terminal_outcome": outcome, "timestamp": ts }`.

## 8. Atomicity Boundary
- Temporary directory created inside `data/output/`.
- File descriptors flushed (`flush()`) and synced (`os.fsync()`) before atomic atomic rename (`os.replace()`).

## 9. Required Logs
- Initial check: `[Idempotency] key=<key> dedupe_hit=<bool> terminal_outcome=<outcome>`
- Batch completion: `[OK] Processed <N> new DNA strings. Total in ledger: <M>`

## 10. Grep Recipes
- Check idempotency hits: `grep "dedupe_hit=True" logs.txt`
- Check processing errors: `grep "terminal_outcome=error" data/processed_ledger.json`
