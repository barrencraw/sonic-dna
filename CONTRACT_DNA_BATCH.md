# Chain Contract: DNA Batch Parsing

**Chain Name:** DNA Batch Parsing

## Description
Processes a batch of DNA strings from an input file, parses them using defined rules, and appends the results to cumulative JSON and CSV datasets. It uses a ledger to ensure idempotency.

## Trigger
- CLI: `python3 main.py --once`
- Watcher: Triggered by changes to `data/raw/toSequence.txt`

## Inputs
- `data/raw/toSequence.txt`: Raw DNA strings (one per line).
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Idempotency ledger.
- `data/output/toSequence_parsed.json`: Cumulative JSON results.
- `data/output/toSequence_parsed.csv`: Cumulative CSV results.

## Terminal States
- **SUCCESS**: New DNA parsed, results appended to all output files, ledger updated, and input file cleared.
- **ERROR**: Process failed at any stage. Permanent files remain unchanged. Input file is NOT cleared.

## Invariants
- **Consistency**: A DNA string in the ledger must exist in both JSON and CSV outputs.
- **Idempotency**: Processing the same DNA string multiple times has no additional side effects.
- **Atomicity**: JSON output, CSV output, and Ledger must be updated as a single atomic unit.

## Error Classes
- `RuleLoadError`: Failed to load parsing rules.
- `DNAProcessingError`: Generic error during DNA reading or parsing.
- `PersistenceError`: Failed to write outputs atomically.

## Idempotency Key
- The raw DNA string.

## Atomicity Boundary
- The "Commit" phase where temporary files for JSON, CSV, and Ledger are moved to their final locations using `os.replace`.

## Required Logs
- `[START] Starting DNA batch processing...`
- `[Idempotency] key={key} dedupe_hit={True/False} terminal_outcome={outcome}`
- `[OK] Processed {n} new DNA strings.`
- `[END] Batch processing complete.`
- `[ERROR] {error_message}`
