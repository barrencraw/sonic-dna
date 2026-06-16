# CONTRACT: DNA Batch Processing Chain

## Trigger
- **Watcher**: Monitors `data/raw/toSequence.txt` for new lines.
- **CLI**: `python main.py --once` or direct call to `utils/dna_ui.py`.

## Inputs
- DNA sequences listed in `data/raw/toSequence.txt` (one per line).
- Canonical name: `dna_sequence`.

## Terminal States (DNAStatus)
- `success`: Sequence parsed successfully and results persisted.
- `error`: Sequence parsing failed due to rule violation.
- `skipped`: Sequence was previously processed (idempotency hit).
- `processing`: Sequence is currently being handled.

## Invariants
1. **Idempotency**: Every `dna_sequence` is processed at most once. Deduplication is handled via the ledger.
2. **Atomicity**: Partial writes are prevented. Output files (`.json`, `.csv`) and the `ledger.json` are updated using atomic file replacement (`os.replace`).
3. **Thermal Fatigue**: System prevents overheating. Each processed item adds heat; processing is refused if `MAX_HEAT` is reached.

## Error Classes
- `RuleParseError`: Malformed DNA string.
- `PersistenceError`: Failure during atomic file write or rename.
- `ThermalOverloadError`: System heat exceeds `MAX_HEAT`.

## Idempotency Key
- The raw `dna_sequence` string itself.

## Atomicity Boundary
- Atomic updates to `data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`, and `data/ledger.json`.

## Required Logs
- Each step must emit a JSON log prefixed with `JSON_LOG:`.
- Must include: `timestamp`, `correlation_id`, `step`, `outcome`, `latency_ms`.
