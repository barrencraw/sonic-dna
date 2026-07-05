# DNA Batch Processing Chain Contract

## Overview
Hardened batch processing for DNA sequences with idempotency, atomicity, and structured telemetry.

## Contract
- **Trigger**: Addition of lines to `data/raw/toSequence.txt` or manual invocation of `main.py --once`.
- **Inputs**: DNA strings (prefixed codes like `VOL...`, `V...`).
- **Terminal States**:
    - `SUCCESS`: Parsed successfully.
    - `ERROR`: Parsing failed (recorded in ledger).
    - `SKIPPED`: Already processed (idempotency hit).
    - `REFUSED`: Hardware/Policy rejection (e.g., Thermal Lockout).
- **Invariants**:
    - **No Silent Drains**: Input file is only cleared if the batch commit succeeds.
    - **Atomic Commit**: Ledger, JSON, and CSV outputs are updated in a single transaction.
- **Error Classes**:
    - `RuleParseError`: Malformed DNA.
    - `PersistenceError`: Failure to write or rename output files.
    - `RuleLoadError`: Rules folder missing or corrupted.
- **Idempotency Key**: The raw DNA string.
- **Atomicity Boundary**: Multi-file `os.replace` in `utils/dna_ui.py`.

## Telemetry
Logs are prefixed with `JSON_LOG:` for easy parsing.
- **Required Fields**: `timestamp`, `correlation_id`, `step`, `outcome`.

### Grep Recipe
```bash
grep 'JSON_LOG:' | sed 's/JSON_LOG: //' | jq '.'
```
Analyze specific batch:
```bash
grep "CORRELATION_ID" | grep 'JSON_LOG:' | sed 's/JSON_LOG: //' | jq -s '.'
```
