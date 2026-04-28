# DNA Batch Parsing Chain Contract

## Goal
Reliably parse batches of DNA strings into structured JSON/CSV data with idempotency, atomicity, and deep observability.

## Win Condition
Successfully process new DNA strings from `toSequence.txt`, updating cumulative outputs and the ledger atomically, while maintaining a Fatigue (thermal) system.

## Done When
- [ ] DNA strings are parsed into the canonical `ParsedDNA` DTO.
- [ ] Processing is idempotent: already processed DNA strings are skipped.
- [ ] Outputs (JSON, CSV, Ledger) are updated atomically (all or nothing).
- [ ] Telemetry logs use `| TELEMETRY |` prefix and structured JSON with correlation IDs.
- [ ] Fatigue system correctly applies heat for VOL strings and natural cooling for each batch.

## Contract
- **Trigger**: File modification to `data/raw/toSequence.txt` or manual `--once` run.
- **Inputs**: List of DNA strings.
- **Terminal States**: `SUCCESS`, `ERROR`, `PARTIAL_SUCCESS`, `NO_NEW_DNA`.
- **Invariants**:
    - Input file `toSequence.txt` is only cleared if processing succeeds.
    - Ledger is only updated if outputs are successfully persisted.
- **Error Classes**: `RuleLoadError`, `PersistenceError`, `RuleParseError`, `ThermalOverloadError`.
- **Idempotency Key**: The raw DNA string.
- **Atomicity Boundary**: The commit of `toSequence_parsed.json`, `toSequence_parsed.csv`, and `processed_ledger.json`.
- **Telemetry Schema**: `{"timestamp": "...", "correlation_id": "...", "chain_name": "dna_batch_chain", "step": "...", "outcome": "...", "actor_id": "system"}`

## Telemetry Triage (Grep Recipes)
- Find errors: `grep "| TELEMETRY |" | grep "ERROR"`
- Check completions: `grep "| TELEMETRY |" | grep "END"`
- Trace a specific batch: `grep "<CORRELATION_ID>" <log_file>`
