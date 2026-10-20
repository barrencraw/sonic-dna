# Mini Chain Contract: DNA Batch Parsing & Ledger Pipeline

## 1. Trigger
- Background file watcher monitoring `data/raw/toSequence.txt` (`main.py`).
- One-time CLI batch parser command (`python main.py --once`).
- Direct programmatic invocation (`utils.dna_ui.main()` / `run_batch()`).

## 2. Inputs
- `data/raw/toSequence.txt`: Raw text file containing one DNA sequence per line (e.g. `VOL08900750712`).
- `data/processed_ledger.json`: Persistent ledger JSON tracking already processed DNA sequences and their terminal state.
- `rules/*.json`: Rule specification JSON files loaded by `DNACalculator`.

## 3. Terminal States
- `success`: DNA sequence successfully matched a rule and parsed values. Recorded in output JSON/CSV and ledger.
- `error`: DNA sequence failed rule parsing (`RuleParseError`). Recorded in output JSON/CSV with error detail and tracked in ledger.
- `skipped`: DNA sequence already present in `processed_ledger.json` (idempotency deduplication hit). Skipped without duplicate output entries.

## 4. Invariants
- **Deduplication:** A DNA sequence with an existing ledger entry is never re-parsed or duplicated in output JSON or CSV files.
- **Atomicity:** File updates (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`) are committed atomically via temporary directory writes (`fsync`) and atomic replacements (`os.replace`). Output files are never left partially written.
- **Data Preservation:** On batch failure (e.g., IO/Persistence exception), input file `toSequence.txt` is not cleared by `main.py`, preserving unprocessed data for retry.
- **Ledger-Output Consistency:** The ledger state and output files are updated in step only when `new_processed_count > 0`.

## 5. Error Classes
- `DNAProcessingError`: Base exception class for DNA pipeline errors.
- `RuleLoadError`: Raised when rules directory cannot be read or parsed.
- `PersistenceError`: Raised when writing temporary files, syncing, or replacing output files fails.

## 6. Idempotency Key Strategy
- **Key:** Raw DNA sequence string (e.g. `VOL08900750712` or `V100`).
- **Store:** `data/processed_ledger.json`.
- **Logic:** Before parsing a sequence, check if `key in ledger`. If `True`, emit dedupe log and skip sequence.

## 7. Atomicity Boundary
- Writes to `toSequence_parsed.json` and `toSequence_parsed.csv` occur inside a temporary directory created within `data/output/`.
- File handles are flushed (`jf.flush()`) and synced to physical storage (`os.fsync()`) before calling `os.replace()` to atomically move temporary files into place.
- Ledger is updated and persisted atomically.

## 8. Required Logs
- **Start / Check:** `[Idempotency] key={key} dedupe_hit=False terminal_outcome=processing`
- **Dedupe Hit:** `[Idempotency] key={key} dedupe_hit=True terminal_outcome={outcome}`
- **Completion Step:** `[Idempotency] key={key} dedupe_hit=False terminal_outcome={outcome}`
- **Batch End:** `[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {total_ledger_size}`

## 9. Grep Recipes
```bash
# Monitor idempotency hits and outcomes
grep -E "\[Idempotency\]" log.txt

# Monitor batch summary logs
grep -E "\[OK\]|\[ERROR\]|\[WARN\]" log.txt
```
