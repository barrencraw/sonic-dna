# SonicDNA Chain Contract: DNA Batch Parsing

## Trigger
- **Background Watcher (`main.py`):** Monitors `data/raw/toSequence.txt` for non-empty content.
- **CLI One-Time Execution (`main.py --once`):** Parses all lines currently in `data/raw/toSequence.txt` once.

## Inputs
- **Input Queue File:** `data/raw/toSequence.txt` (UTF-8 text file containing one DNA string per line).
- **Rulesets:** JSON rules files located in `rules/` (e.g., `rules_Volume.json`, `rules_Timbre.json`).

## Terminal States
- **SUCCESS:** All new DNA sequences are parsed and committed atomically to `data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`, and `data/processed_ledger.json`. Input queue `toSequence.txt` is cleared by caller (`main.py`).
- **ERROR:** A processing error or atomic persistence failure occurs. Output files are unchanged, and the input file `toSequence.txt` is retained for retry/investigation.

## Invariants
1. **Idempotency:** Re-invoking batch parsing on already processed DNA sequences skips re-parsing and produces no duplicate output records.
2. **Atomicity Boundary:** Either all outputs (JSON, CSV, Ledger) are committed together, or none are modified. No partial or torn writes.
3. **No Queue Truncation on Failure:** `toSequence.txt` is truncated ONLY after a successful return from `run_batch()`.

## Error Taxonomy
- `DNAProcessingError` (Base exception class)
- `RuleLoadError` (Subclass of `DNAProcessingError` — raised when rule JSON files cannot be loaded)
- `PersistenceError` (Subclass of `DNAProcessingError` — raised when atomic file operations fail)
- `RuleParseError` (Raised when a DNA string fails to parse according to rulesets; recorded as an error entry in the batch output)

## Idempotency Key Strategy
- **Key:** The raw DNA sequence string (e.g., `VOL08900750712`).
- **Store:** `data/processed_ledger.json` maps each idempotency key to its `terminal_outcome` (`success` or `error: <details>`) and UTC ISO `timestamp`.

## Atomicity Boundary Implementation
- All output files (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`) are written into a temporary directory created within the `data/` directory (`tempfile.TemporaryDirectory(dir=data_folder)`).
- File buffers are flushed (`flush()`) and synced to physical storage (`os.fsync()`) before commitment.
- Final commit is executed via atomic renames (`os.replace()`).

## Required Logs & Grep Recipes

### Telemetry / Log Format
- `[Idempotency] key=<dna_string> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `[OK] Processed <count> new DNA strings. Total in ledger: <total>`

### Grep Recipes
```bash
# Check deduplication hits
grep "dedupe_hit=True" logs/output.log

# Track new processing outcomes
grep "dedupe_hit=False" logs/output.log

# Find persistence errors
grep "PersistenceError" logs/output.log
```
