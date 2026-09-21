# Chain Contract: DNA Batch Parsing

## 1. Overview & Goal
The **DNA Batch Parsing** chain ingests raw DNA sequences from `data/raw/toSequence.txt`, parses each sequence using rules defined in `rules/rules_*.json`, records terminal outcomes in `data/processed_ledger.json`, and outputs structured JSON and CSV datasets to `data/output/`.

## 2. Trigger
- **Watcher (`main.py`)**: Continuously monitors `data/raw/toSequence.txt`. On detecting non-empty content changes, invokes `run_batch()`.
- **CLI (`main.py --once`)**: Invokes `process_once()` to execute `run_batch()` exactly once without starting the GUI or background watcher loop.

## 3. Inputs
- `data/raw/toSequence.txt`: Newline-separated DNA sequences (e.g. `VOL08900750712`).
- `rules/rules_*.json`: Rule specification JSON files loaded by `DNACalculator`.
- `data/processed_ledger.json`: Persistent ledger tracking previously processed idempotency keys.

## 4. Terminal States
- **SUCCESS**: All new DNA sequences are parsed, recorded in `data/processed_ledger.json`, and written atomically to `data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`. The input file `toSequence.txt` is cleared by the watcher upon success.
- **ERROR**: Raised when input reading, rule loading, ledger access, or atomic file write fails. Output files are protected against partial/torn writes via temporary staging directories and atomic renames. The input file `toSequence.txt` is retained for retry investigation.
- **SKIPPED**: All DNA sequences in `toSequence.txt` match existing ledger entries (`dedupe_hit=True`). No atomic write or output file mutation occurs.

## 5. Invariants
- **Atomicity Boundary**: Staged outputs are written to temporary files inside a temporary directory in the output path, flushed (`jf.flush()`), synced (`os.fsync()`), and atomically renamed (`os.replace()`).
- **Idempotency**: Every processed DNA sequence uses the raw sequence string as its `idempotency_key`. Subsequent invocations skip already-processed sequences without duplicating output entries.
- **Backwards & Canonical Compatibility**: All output JSON and CSV records export both `dna` and `dna_sequence` field names. Ledger lookup supports legacy flat ledgers as well as nested dictionary structures (`ledger.get('ledger', ledger)`).

## 6. Error Taxonomy
```
DNAProcessingError (Base Class)
├── InputReadError
├── RuleLoadError
└── PersistenceError
    ├── LedgerLoadError
    ├── LedgerSaveError
    └── AtomicWriteError
```

## 7. Required Logs & Telemetry Format
Structured telemetry entries are emitted to standard output with a `JSON_LOG:` prefix.
Mandatory fields:
- `timestamp`: UTC ISO 8601 string (e.g., `2026-03-02T15:00:00Z`)
- `correlation_id`: Unique trace ID or `"N/A"`
- `actor_id`: Initiator identifier (e.g., `"batch_parser"`)
- `chain_name`: `"dna_batch_parsing"`
- `step`: Lifecycle step (e.g., `"start"`, `"dedupe_check"`, `"parse_sequence"`, `"atomic_commit"`, `"complete"`, `"error"`)
- `outcome`: Outcome status (`"success"`, `"error"`, `"skipped"`)
- `latency_ms`: Elapsed execution time in milliseconds
- `idempotency_key`: Raw DNA sequence string or sequence list summary
- `outcome_detail`: Descriptive detail or exception message

## 8. Grep Recipes
- View all structured telemetry logs:
  ```bash
  grep "JSON_LOG:" logs.txt
  ```
- Filter structured logs by correlation ID:
  ```bash
  grep "JSON_LOG:" logs.txt | grep "<correlation_id>"
  ```
- Extract idempotency status using jq:
  ```bash
  grep "JSON_LOG:" logs.txt | sed 's/^JSON_LOG: //' | jq '. | {idempotency_key, outcome, step}'
  ```
