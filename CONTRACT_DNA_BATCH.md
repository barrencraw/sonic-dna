# Chain Contract: DNA Batch Processing (`dna_batch_chain`)

## Trigger
- Manual execution via `python main.py --once`
- Automatic execution via background watcher in `main.py` monitoring `data/raw/toSequence.txt`.

## Inputs
- **Primary Input:** `data/raw/toSequence.txt` (Newline-delimited DNA strings).
- **Secondary Input:** `data/processed_ledger.json` (Existing idempotency ledger).
- **Static Input:** `rules/*.json` (Grammar for parsing).

## Terminal States
- **SUCCESS:** DNA string parsed and added to output dataset.
- **ERROR:** DNA string failed parsing; error recorded in output dataset.
- **SKIPPED:** DNA string already exists in ledger; no redundant processing.

## Invariants
- **Idempotency:** A DNA string processed once (as SUCCESS or ERROR) shall not be processed again if it exists in the ledger.
- **Atomicity:** The commitment of JSON output, CSV output, and the Ledger update must be atomic. If any write fails, none of the files shall be updated on disk.
- **Deduplication:** Multiple identical DNA strings within a single batch submission are treated as one unique request.

## Error Classes
- `RuleLoadError`: Critical failure to load JSON rules.
- `RuleParseError`: Individual DNA string is malformed (Terminal: ERROR).
- `PersistenceError`: IO failure during the atomic commit phase.

## Observability (Telemetry)
Standard log format: `[dna_batch_chain] key=<dna_string> dedupe_hit=<True|False> outcome=<SUCCESS|ERROR|processing>`

## "Done When"
- [ ] Processing loop correctly updates the in-memory ledger for ALL items in a batch.
- [ ] JSON, CSV, and Ledger are written to a temporary directory and moved to final destination via `os.replace`.
- [ ] Redundant write calls are removed from `utils/dna_ui.py`.
- [ ] Indentation and syntax errors in `utils/dna_ui.py` are resolved.
- [ ] `test_atomicity.py` passes and includes ledger consistency checks.
