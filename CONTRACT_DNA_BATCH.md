# Chain Contract: DNA Batch Parsing

## Description
This chain processes a batch of DNA strings from an input file and persists the results into multiple cumulative formats while maintaining an idempotency ledger.

## Trigger
- Watcher detects non-empty content in `data/raw/toSequence.txt`.
- Manual invocation via `python3 main.py --once`.

## Inputs
- `data/raw/toSequence.txt`: A file containing one DNA string per line.

## Terminal States
- **SUCCESS**: All new DNA strings parsed and recorded in JSON, CSV, and Ledger.
- **ERROR**: A fatal error occurred during rule loading, file reading, or atomic persistence.
- **NO_NEW_DNA**: Input file was empty or all strings were already processed.

## Invariants
- **Idempotency**: A DNA string already present in `processed_ledger.json` will not be re-processed or added again to the output files.
- **Atomicity**: The updates to `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` are atomic. Either all three are updated, or none are.
- **Deduplication**: In-memory deduplication of the current batch ensures even duplicate lines in `toSequence.txt` only result in one processing event.

## Error Classes
- `RuleLoadError`: Rules folder or files could not be loaded.
- `RuleParseError`: A specific DNA string does not conform to any loaded rule.
- `PersistenceError`: Failed to write output files atomically to disk.
- `DNAProcessingError`: Generic failure in the processing pipeline.

## Idempotency Key
- The **DNA string** itself is the unique key.

## Atomicity Boundary
- All cumulative output files (`.json`, `.csv`) and the state ledger (`.json`) must be committed together using a temporary-directory-and-rename pattern.

## Required Telemetry Logs
- `[START] dna_batch_chain correlation_id=<uuid> actor_id=<actor>`
- `[STEP] processing_dna key=<dna_string>`
- `[Idempotency] key=<dna_string> dedupe_hit=<bool> terminal_outcome=<outcome>`
- `[END] dna_batch_chain outcome=<outcome> latency_ms=<ms>`

## Grep Recipe
`grep -E "\[START\]|\[STEP\]|\[Idempotency\]|\[END\]" data/logs/observability.log` (or stdout)
