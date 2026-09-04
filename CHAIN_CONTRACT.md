# Chain Contract: DNA Batch Parsing (`dna_batch_parse`)

## Overview
The `dna_batch_parse` chain handles batch ingestion, parsing, thermal safety enforcement, and atomic persistence of audio DNA sequences.

## 1. Trigger
- **Watcher Trigger**: Automatic execution on file modification detected in `data/raw/toSequence.txt`.
- **CLI/Direct Trigger**: Execution via `python main.py --once` or direct call to `utils.dna_ui.run_batch(correlation_id, actor_id)`.

## 2. Inputs
- `input_file`: Path to raw DNA input file (`data/raw/toSequence.txt`), containing line-delimited DNA sequences.
- `rules_folder`: Path to JSON rules definitions (`rules/`).
- `ledger_path`: Path to ledger persistence file (`data/processed_ledger.json`).
- `output_folder`: Path to output directory (`data/output/`).
- `correlation_id`: Trace UUID string.
- `actor_id`: String identifier for execution caller (default: `'batch_parser'`).

## 3. Terminal States
The chain resolves each input DNA sequence into one of four standardized lowercase terminal states (`DNAStatus` enum):
- `success`: Sequence successfully parsed against rule definitions and appended to JSON/CSV output.
- `error`: Sequence parsing failed due to invalid prefix, truncated format, or bad parameters (`RuleParseError`), recorded as an error entry.
- `skipped`: Sequence key was already present in the ledger with a terminal outcome and bypassed processing.
- `refused`: Sequence execution was blocked due to Thermal Fatigue lockout (`ThermalOverloadError`).

## 4. Invariants
- **Idempotency**: Input DNA sequences with terminal outcomes in `processed_ledger.json` are never re-parsed or duplicated in output files.
- **Atomicity**: Partial or torn writes to output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) or ledger are impossible.
- **No Silent Drains**: Input file (`toSequence.txt`) is preserved and NOT cleared when parsing fails or is refused due to thermal lockout.
- **Thermal Dissipation**: Core heat accumulates by 2.0 heat units per successfully parsed sequence and dissipates at 0.5 heat units per second based on UTC timestamps. Threshold is 10.0 heat units.

## 5. Error Taxonomy
```
DNAProcessingError (Base)
├── RuleLoadError
├── InputReadError
├── PersistenceError
│   ├── LedgerLoadError
│   ├── LedgerSaveError
│   └── AtomicWriteError
└── ThermalOverloadError
```

## 6. Idempotency Key Strategy
- Key: Exact raw string of the DNA sequence (e.g., `"VOL08900750712"`).
- Ledger Schema:
```json
{
  "ledger": {
    "VOL08900750712": {
      "terminal_outcome": "success",
      "timestamp": "2026-03-02T10:00:00Z"
    }
  },
  "system_state": {
    "core_heat": 2.0,
    "last_processed_timestamp": "2026-03-02T10:00:00Z"
  }
}
```

## 7. Atomicity Boundary
- Output files (`toSequence_parsed.json`, `toSequence_parsed.csv`) are generated in a temporary directory inside `data/output/`, flushed (`jf.flush()`), synced to disk (`os.fsync()`), and atomically renamed (`os.replace()`) to target paths.
- Output files are only updated if `new_processed_count > 0`.

## 8. Required Logs
Structured JSON telemetry logs are printed to stdout prefixed with `JSON_LOG:`:
- Fields: `timestamp` (UTC ISO 8601), `correlation_id`, `actor_id`, `chain_name`, `step`, `outcome`, `latency_ms`, `idempotency_key`, `outcome_detail`.

## 9. Grep Recipes
- View all structured telemetry logs:
  `grep "JSON_LOG:" app.log`
- View all thermal lockout refusals:
  `grep "JSON_LOG:" app.log | grep '"outcome": "refused"'`
- Trace a specific run by correlation ID:
  `grep "JSON_LOG:" app.log | grep '"correlation_id": "<UUID>"'`
- Find all deduplication hits (skipped items):
  `grep "JSON_LOG:" app.log | grep '"step": "deduplication"'`
