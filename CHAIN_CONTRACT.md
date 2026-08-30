# SonicDNA Chain Contract: DNA Batch Parsing

## 1. Trigger
- **Automated Watcher**: Background thread monitoring `data/raw/toSequence.txt` (`main.py:watch_loop`).
- **Manual / CLI Single Run**: One-time invocation via `python main.py --once` (`main.py:process_once`).
- **Direct Code Invocations**: Calling `utils.dna_ui.run_batch(correlation_id=...)`.

## 2. Inputs
- Path: `data/raw/toSequence.txt`
- Format: UTF-8 encoded text file with one DNA sequence per line (e.g. `VOL08900750712`).
- Context Parameters: `correlation_id` (UUID string), `actor_id` (string, e.g. `'batch_parser'`).

## 3. Terminal States
- `success`: DNA sequence successfully matched a rule, parsed into nested values, and recorded.
- `error`: DNA sequence failed rule parsing (e.g., `RuleParseError`) or formatting check; error state recorded in ledger and output.
- `skipped`: DNA sequence key already exists in `processed_ledger.json` with terminal outcome (`success` or `error`).

## 4. Invariants
- **Atomic Persistence**: Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) and `processed_ledger.json` are committed atomically. Partial or torn writes never reach disk.
- **Deduplication / Idempotency**: Submitting identical DNA sequences multiple times yields no duplicate entries in outputs.
- **Queue Protection**: Input file (`data/raw/toSequence.txt`) is cleared ONLY if batch execution completes without unhandled exceptions.
- **Backwards Compatibility**: Both `dna` and `dna_sequence` keys are present in output json entries to maintain compatibility across historical and modern clients.

## 5. Error Taxonomy
```
DNAProcessingError (Exception)
 ├── RuleLoadError
 ├── InputReadError
 └── PersistenceError
      ├── LedgerLoadError
      ├── LedgerSaveError
      └── AtomicWriteError
```

## 6. Idempotency Key Strategy
- **Key**: The normalized raw DNA sequence string (`dna_str.strip()`).
- **Ledger Path**: `data/processed_ledger.json`.
- **Deduplication Check**: Before running `calculator.parse()`, `utils.dna_ui.run_batch()` checks if key is in the ledger.

## 7. Atomicity Boundary
- Output files are written to a temporary directory inside `data/output/`.
- File descriptors are explicitly flushed (`jf.flush()`) and synced (`os.fsync(jf.fileno())`).
- Destination files are replaced using atomic filesystem rename (`os.replace()`).

## 8. Required Telemetry Logs
- Structured logs are printed to stdout prefixed with `JSON_LOG:`.
- Format:
```json
{
  "timestamp": "2025-06-02T12:00:00Z",
  "correlation_id": "c1a2b3c4-...",
  "actor_id": "batch_parser",
  "chain_name": "dna_batch_parse",
  "step": "parse_sequence",
  "outcome": "success",
  "latency_ms": 1.23,
  "idempotency_key": "VOL08900750712",
  "outcome_detail": "Parsed rule Volume"
}
```

## 9. Grep Recipes
- View all structured telemetry logs:
  `grep "JSON_LOG:" application.log`
- View all errors during batch execution:
  `grep "JSON_LOG:" application.log | grep '"outcome":"error"'`
- Trace a specific request by correlation ID:
  `grep "JSON_LOG:" application.log | grep '"correlation_id":"<UUID>"'`
