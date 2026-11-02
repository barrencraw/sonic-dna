# Mini Chain Contract: DNA Batch Parsing

## 1. Trigger
- **Automated Watcher:** Background thread in `main.py` monitoring `data/raw/toSequence.txt` for non-empty content changes.
- **Manual Execution:** CLI command `python3 main.py --once`.

## 2. Inputs
- `data/raw/toSequence.txt`: Raw DNA sequence strings (one per line, UTF-8 encoded).
- `rules/rules_*.json`: Domain rule definitions loaded by `DNACalculator`.
- `data/processed_ledger.json`: Persistent execution record tracking completed sequences.

## 3. Terminal States
- `SUCCESS`: All new DNA sequences successfully parsed and persisted.
- `NO_NEW_DNA`: Input file is empty or all sequences have already been processed according to the ledger.
- `ERROR`: A recoverable or fatal failure occurred during rule loading, reading, or persistence.

## 4. Invariants
- **Strict Idempotency:** Any DNA sequence previously recorded in `data/processed_ledger.json` is deduplicated and not reprocessed.
- **Atomicity:** JSON output (`toSequence_parsed.json`), CSV output (`toSequence_parsed.csv`), and ledger (`processed_ledger.json`) must be committed together atomically. If an I/O or system failure occurs mid-write, none of the target files are partially overwritten.
- **Queue Drain Safety:** The input file `toSequence.txt` is truncated/cleared if and only if batch processing and persistence complete successfully.

## 5. Error Classes
- `DNAProcessingError`: Base exception for domain and batch processing errors.
- `RuleLoadError`: Subclass of `DNAProcessingError`, raised when rule definitions fail to load.
- `PersistenceError`: Subclass of `DNAProcessingError`, raised when writing or atomic renames fail.

## 6. Idempotency Key
- The raw DNA string (e.g. `VOL08900750712`).

## 7. Atomicity Boundary
- All output files (`output.json`, `output.csv`, `ledger.json`) are written, flushed, and synced (`os.fsync`) inside an isolated temporary directory within the destination filesystem.
- Upon successful synchronization, files are atomically swapped into place via `os.replace`.

## 8. Required Logs & Grep Recipe
Structured logs are emitted with the prefix `JSON_LOG:` or standard tagged log levels:
- Log fields: `timestamp`, `correlation_id`, `actor_id`, `chain_name`, `step`, `outcome`, `latency_ms`, `idempotency_key`.

### Grep Recipe:
```bash
grep -E "JSON_LOG:" app.log
grep -E "\[Idempotency\]|\[Watcher\]" app.log
```
