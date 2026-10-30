# Chain Contract: DNA Batch Parsing

## 1. Overview & Scope
The **DNA Batch Parsing Chain** is the core data ingestion and processing pipeline in SonicDNA. It converts structured DNA sequence strings from `data/raw/toSequence.txt` into formatted JSON (`toSequence_parsed.json`) and CSV (`toSequence_parsed.csv`) outputs, while tracking processed sequences in `data/processed_ledger.json`.

---

## 2. Trigger
- **Watcher Event**: File change detection loop in `main.py` monitoring `data/raw/toSequence.txt`.
- **Manual / CLI Trigger**: One-time batch run via `python main.py --once` or direct import and execution of `utils.dna_ui.run_batch()`.

---

## 3. Inputs
- Path: `data/raw/toSequence.txt`
- Format: UTF-8 text file, one DNA sequence string per line (e.g., `VOL08900750712`).
- Parameter: Optional `correlation_id` string for tracing execution contexts.

---

## 4. Terminal States
- `success`: DNA sequence parsed successfully against matching rules in `rules/`, added to outputs, and recorded in ledger.
- `error`: DNA sequence failed parsing (`RuleParseError`), error recorded in output structures and ledger.
- `skipped`: DNA sequence key already exists in `data/processed_ledger.json` with a terminal outcome (`success` or `error`).

---

## 5. Invariants
1. **Idempotency Guarantee**: Submitting the same DNA string multiple times yields no duplicate entries in outputs or redundant calculations.
2. **Atomic Write Boundary**: Output JSON and CSV files are written to a temporary directory in the output filesystem, flushed, synced (`fsync`), and atomically replaced (`os.replace`).
3. **No Loss Input Drain**: Input file `toSequence.txt` is cleared/truncated if and only if batch processing succeeds without raising persistence errors.
4. **Ledger Consistency**: Ledger updates reflect only finalized processing outcomes.

---

## 6. Error Taxonomy
- `DNAProcessingError` (Base Class): General DNA processing failure.
- `RuleLoadError` (Subclass): Rules folder or rules definition files missing or invalid.
- `PersistenceError` (Subclass): Temporary file write, sync, or replace operation failed.
- `RuleParseError` (External Domain Exception): Unrecognized prefix or malformed variable segment within a DNA sequence string.

---

## 7. Idempotency Key Strategy
- **Key**: The raw DNA sequence string (`dna_str`).
- **Store**: `data/processed_ledger.json`.
- **Lookup**: `key in ledger` check performed prior to invoking calculator logic.

---

## 8. Atomicity Boundary
The atomic transaction boundary spans:
1. Load existing ledger and cumulative JSON/CSV data.
2. Process all non-deduplicated DNA strings.
3. Write JSON and CSV outputs to a temporary directory inside `data/output/`.
4. Flush file buffers and issue `os.fsync()`.
5. Write updated ledger state to `data/processed_ledger.json`.
6. Perform atomic file replacement (`os.replace`) for `toSequence_parsed.json` and `toSequence_parsed.csv`.
7. Clear input file `data/raw/toSequence.txt` in calling wrapper (`main.py`) upon successful batch return.

---

## 9. Telemetry & Observability Logs
### Log Schema
- **Start**: `[Start] chain=dna_batch_parser correlation_id=<id> input_count=<count>`
- **Step / Idempotency**: `[Idempotency] key=<key> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- **End**: `[End] chain=dna_batch_parser processed_count=<count> total_ledger=<total>`

### Grep Recipes
Search for batch events:
```bash
grep -E "\[(Start|Step|End|Idempotency)\]" logs.txt
```
Filter idempotency deduplication hits:
```bash
grep "dedupe_hit=True" logs.txt
```
