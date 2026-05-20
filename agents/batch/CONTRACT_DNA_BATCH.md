# DNA Batch Chain Contract

## Overview
The DNA Batch Parser is the core data processing path of SonicDNA. It is responsible for reading raw DNA strings, parsing them according to modular rules, and persisting the results in multiple formats while maintaining strict idempotency and atomicity invariants.

## Trigger
- **Watcher (`main.py`)**: Continuously monitors `data/raw/toSequence.txt`.
- **Manual Batch (`utils/dna_ui.py`)**: Executed directly or via `--once` flag in `main.py`.

## Inputs
- `data/raw/toSequence.txt`: Raw DNA strings (one per line).
- `rules/*.json`: Modular parsing rules for various audio properties.
- `data/processed_ledger.json`: The idempotency ledger.

## Terminal States (`TerminalOutcome`)
- `SUCCESS`: DNA string parsed successfully and recorded.
- `PARSE_ERROR`: DNA string failed validation/parsing; error recorded.
- `SKIPPED`: DNA string already present in the ledger; no redundant processing.

## Invariants
- **Idempotency**: No DNA string is processed more than once. The DNA string itself serves as the `idempotency_key`.
- **Atomicity**: Changes to the JSON output, CSV output, and the Ledger are committed as a single unit using an atomic rename pattern.
- **Consistency**: Cumulative outputs (`.json`, `.csv`) and the ledger are kept in sync. If a crash occurs during I/O, no partial state is committed.
- **Non-Destructive**: Input file is only cleared by the caller if the batch process completes successfully.

## Error Classes
- `RuleLoadError`: Critical failure to load rule definitions.
- `RuleParseError`: Handled failure to parse a specific string (results in `PARSE_ERROR`).
- `PersistenceError`: Critical failure during the atomic write/commit phase.

## Idempotency Key
- The raw DNA string (e.g., `VOL08900750712`).

## Atomicity Boundary
- `data/output/toSequence_parsed.json`
- `data/output/toSequence_parsed.csv`
- `data/processed_ledger.json`

## Required Logs
- `[Idempotency] key={key} dedupe_hit={True|False} terminal_outcome={outcome}`
- `[OK] Processed {n} new DNA strings.`
- `[ERROR] ...` or `[CRITICAL] ...` for fatal failures.

## Telemetry Grep Recipes
- **Find failed parses**: `grep "terminal_outcome=PARSE_ERROR" logs.txt`
- **Check deduplication hits**: `grep "dedupe_hit=True" logs.txt`
- **Verify batch completion**: `grep "\[OK\] Processed" logs.txt`
