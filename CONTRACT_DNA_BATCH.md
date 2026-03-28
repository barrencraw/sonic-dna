# DNA Batch Processing Contract

## Naming Standards
- **DTO**: `ParsedDNA` (defined in `utils/dna_calculator.py`)
- **Processing Result**: `ProcessingResult` (defined in `utils/dna_ui.py`)
- **Outcome Enum**: `Outcome` (SUCCESS, ERROR, SKIPPED, START, END, NO_NEW_DNA, WARN)

## Error Classification
Errors during parsing are classified as `Outcome.ERROR` and recorded in the ledger and JSON/CSV outputs with the specific error message.

## Observability
All significant events in the `dna_batch_chain` are logged as structured JSON prefixed with `[OBSERVABILITY]`.

### Required Fields
- `timestamp`: ISO8601 UTC
- `correlation_id`: Unique ID for the batch run
- `actor_id`: 'watcher', 'once_runner', or 'manual'
- `chain_name`: 'dna_batch_chain'
- `step`: 'batch_init', 'process_dna', 'batch_complete'
- `outcome`: one of the `Outcome` enum values
- `latency_ms`: (Optional) processing time in milliseconds
- `idempotency_key`: (Optional) the DNA string being processed
- `error`: (Optional) error message if outcome is ERROR

## Atomicity Boundary
A batch process is considered committed only when the following files are updated atomically:
1. `data/output/toSequence_parsed.json`
2. `data/output/toSequence_parsed.csv`
3. `data/processed_ledger.json`
