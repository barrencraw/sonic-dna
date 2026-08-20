# Mini Chain Contract: DNA Batch Parsing

## Chain Metadata
- **Chain Name:** DNA Batch Parsing
- **Location:** `main.py` (Watcher / Once-Runner) and `utils/dna_ui.py` (`run_batch` / `main`)

## Trigger & Inputs
- **Trigger:**
  - File watcher detection of non-empty `data/raw/toSequence.txt` (`main.py` watcher loop)
  - Manual batch invocation via command line (`python main.py --once`)
  - Direct call to `utils.dna_ui.main()` or `run_batch()`
- **Inputs:**
  - `data/raw/toSequence.txt` (newline-separated DNA sequence strings)
  - `rules/` directory containing JSON variable rulesets (`rules_*.json`)
  - `data/processed_ledger.json` (idempotency ledger)

## Terminal States
- **SUCCESS:**
  - DNA sequences parsed or skipped via deduplication hit.
  - Output files `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv` written atomically.
  - Ledger file `data/processed_ledger.json` updated with new idempotency entries.
  - `toSequence.txt` cleared (truncated) when triggered via `main.py`.
- **ERROR:**
  - `RuleLoadError`, `DNAProcessingError`, or `PersistenceError` raised.
  - Output files and ledger remain uncorrupted (no partial/torn writes).
  - Input file `toSequence.txt` is NOT cleared, preserving data for retry or investigation.

## Invariants
1. **Atomicity:** JSON and CSV outputs and ledger persistence are committed via temporary file staging and `os.replace`. Partial/torn output writes are impossible.
2. **Idempotency:** Re-submitting an already processed DNA sequence string will be deduplicated via `data/processed_ledger.json` without re-parsing or creating duplicate entries in output files.
3. **Queue Preservation:** Input file `toSequence.txt` is only truncated if `run_batch()` completes without exception.

## Error Taxonomy
- `DNAProcessingError`: Base class for DNA batch execution failures.
- `RuleLoadError`: Raised when `DNACalculator` fails to load rule definitions from `rules/`.
- `PersistenceError`: Raised when temporary file staging, flushing, fsyncing, or atomic rename fails.
- `RuleParseError`: Raised by `DNACalculator` for invalid DNA sequence syntax; handled internally per item and recorded as an error outcome in the ledger and output files rather than aborting the entire batch.

## Idempotency Strategy
- **Idempotency Key:** The raw DNA sequence string (`dna_str`).
- **Storage:** `data/processed_ledger.json` mapping `dna_str` -> `{ "terminal_outcome": outcome, "timestamp": timestamp }`.

## Atomicity Boundary
- Output files are written to a temporary directory inside `data/output/`.
- File handles are explicitly flushed (`jf.flush()`) and synced to disk (`os.fsync(jf.fileno())`).
- Atomic rename (`os.replace`) commits temporary files to destination paths (`toSequence_parsed.json` and `toSequence_parsed.csv`).
- Ledger is saved atomically.

## Required Telemetry Logs & Format
Structured logs must follow this format:
- `[Chain:DNA_Batch] [START] correlation_id=<id> total_sequences=<n>`
- `[Chain:DNA_Batch] [STEP:Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `[Chain:DNA_Batch] [END] outcome=<SUCCESS|ERROR> new_processed=<n> total_ledger=<m>`

## Grep Recipes
- Filter all logs for this chain:
  ```bash
  grep "\[Chain:DNA_Batch\]" app.log
  ```
- Find deduplication hits:
  ```bash
  grep "dedupe_hit=True" app.log
  ```
- Check batch completions:
  ```bash
  grep "\[Chain:DNA_Batch\] \[END\]" app.log
  ```
