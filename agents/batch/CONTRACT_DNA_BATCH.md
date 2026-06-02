# Contract: DNA Batch Parsing Chain

## Trigger
- **Manual/Watcher:** Appending DNA strings to `data/raw/toSequence.txt`.
- **CLI:** Running `python main.py --once`.

## Inputs
- `toSequence.txt`: One DNA string per line (e.g., `VOL08900750712`).
- `rules/*.json`: Rule definitions for parsing.
- `data/processed_ledger.json`: Existing state for idempotency.

## Terminal States
- **Success:** DNA strings parsed and appended to JSON/CSV outputs; ledger updated; input file cleared.
- **Dedupe Skip:** DNA string already in ledger; no side effects; skipped.
- **Parse Error:** Malformed DNA string; error recorded in JSON/CSV; ledger updated; input file cleared.
- **Refusal (Atomic Failure):** I/O error during commit; no side effects to final files; input file preserved.

## Invariants
- No torn writes: Final output files are only updated if the entire batch commit succeeds.
- Consistency: JSON and CSV outputs always reflect the same processed set as the ledger.
- Idempotency: Processing the same DNA string multiple times produces no additional side effects.

## Error Classes
- `RuleLoadError`: Missing or corrupt rules.
- `DNAProcessingError`: General batch failure.
- `PersistenceError`: Atomic commit failure (e.g., disk full, permissions).
- `RuleParseError`: Individual DNA string is malformed (handled per-item).

## Idempotency Key
- The raw DNA string itself.

## Atomicity Boundary
- The "Atomic Write Pattern" in `utils/dna_ui.py`: Temporary directory write + Flush + Sync + Multiple `os.replace` calls.

## Required Logs
- Structured logs prefixed with `JSON_LOG:` containing:
    - `timestamp` (ISO 8601)
    - `correlation_id` (UUID)
    - `chain_name` ("dna_batch_parsing")
    - `step` (e.g., "dedupe", "process_item", "commit", "batch_complete")
    - `outcome` (e.g., "start", "success", "error", "skip")
