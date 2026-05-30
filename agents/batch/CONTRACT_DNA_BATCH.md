# Contract: DNA Batch Processing Chain

## Trigger
- **Manual/Watcher**: Addition of non-empty DNA strings to `data/raw/toSequence.txt`.

## Inputs
- `data/raw/toSequence.txt`: Text file, one DNA string per line.
- `rules/*.json`: JSON definitions for DNA parsing rules.
- `data/processed_ledger.json`: Existing ledger for idempotency checks.

## Terminal States
- `success`: Batch completed, new strings processed (or skipped), output and ledger atomically updated.
- `empty`: No DNA strings found in `toSequence.txt`.
- `error`: Fatal failure (e.g., `RuleLoadError`, `PersistenceError`). Input file is NOT cleared.

## Invariants
- **Consistency**: `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json` are updated in a single atomic transaction (via temp folder + `os.replace`).
- **Idempotency**: A DNA string in the ledger is NEVER re-processed or duplicated in the output files.
- **Data Integrity**: Output files are always valid JSON/CSV.

## Error Classes
- `DNAProcessingError`: Generic processing failure.
- `RuleLoadError`: Failed to load or parse rules in `rules/`.
- `PersistenceError`: Failed to write or commit output files atomically.
- `RuleParseError`: Failed to parse an individual DNA string (recorded as an error outcome in ledger/output, does not stop the batch).

## Idempotency Key
- The raw **DNA string** itself.

## Atomicity Boundary
- All output files (`.json`, `.csv`) and the `.json` ledger are written to a temporary directory and moved into place using `os.replace`.

## Required Logs (Structured)
- Prefix: `JSON_LOG: `
- Fields: `timestamp`, `correlation_id`, `chain_name`, `step`, `outcome`, `dna` (optional), `processed` (optional).

### Steps:
1. `start`: `outcome="initiated"`
2. `sequence`: `outcome="success"`, `outcome="skipped"`, or `outcome="error: <msg>"`
3. `persistence`: `outcome="error"` (on atomic write failure)
4. `complete`: `outcome="success"`, `processed=<count>`

## Telemetry Grep Recipes
- **Track Batch Progress**: `grep "JSON_LOG:" | grep "dna_batch"`
- **Check Deduplication Hits**: `grep "JSON_LOG:" | grep "skipped" | grep "idempotency_hit"`
- **Identify Failed Parses**: `grep "JSON_LOG:" | grep "error:"`
