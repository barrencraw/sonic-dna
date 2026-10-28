# Chain Contract: DNA Batch Processing

## 1. Overview & Trigger
- **Chain Name:** `DNA Batch Processing`
- **Trigger:** Invocation of `utils.dna_ui.run_batch()` (or `main()`), either manually via `--once` mode or via background watcher in `main.py` when non-empty content is written to `data/raw/toSequence.txt`.

## 2. Inputs & Data Structures
- **Input File:** `data/raw/toSequence.txt` (text file with 1 DNA sequence per line).
- **Rules Directory:** `rules/*.json` definitions parsed by `DNACalculator`.
- **Processed Ledger:** `data/processed_ledger.json` tracking idempotency keys (`dna_sequence`).

## 3. Idempotency Strategy
- **Idempotency Key:** `dna_sequence` (exact stripped DNA string).
- **Deduplication:** Before parsing, `dna_sequence` is checked against `processed_ledger.json`.
  - If present: Skip processing, log deduplication hit (`dedupe_hit=True`), skip heat accumulation/writes.
  - If absent: Process sequence, record outcome in ledger upon successful batch execution.

## 4. Terminal States & Invariants
- **Terminal States:**
  - `success`: DNA sequence parsed and appended to output JSON and CSV records.
  - `error`: Rule parsing failed (`RuleParseError`); error entry appended to output records.
  - `skipped`: Sequence already recorded in ledger.
- **Invariants:**
  - Zero torn writes: Outputs (`toSequence_parsed.json`, `toSequence_parsed.csv`) and ledger (`processed_ledger.json`) are updated atomically or not at all.
  - No clearing of input file `toSequence.txt` if batch processing fails due to `DNAProcessingError` or system crash.

## 5. Atomicity Boundary
- All output generation is written to a temporary directory in `data/output/`.
- File handles execute `flush()` and `os.fsync()` before committing via `os.replace()`.
- Updates to `processed_ledger.json` only occur after outputs are prepared.

## 6. Error Taxonomy
- `DNAProcessingError` (Base class)
  - `InputReadError`: Failure reading input file `toSequence.txt`.
  - `PersistenceError`: Failure creating, flushing, or replacing output/ledger files atomically.
    - `AtomicWriteError`: Specific failure during atomic temporary file operations.

## 7. Required Telemetry & Logs
- **Start Log:** `[DNA Processing] start batch execution correlation_id=<uuid>`
- **Step Log (Idempotency):** `[Idempotency] key=<dna> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- **End Log:** `[DNA Processing] complete processed=<count> total_ledger=<total>`

## 8. Grep Recipes
- Check deduplication hits:
  `grep "\[Idempotency\]" logs.txt | grep "dedupe_hit=True"`
- Check batch execution start/end:
  `grep "\[DNA Processing\]" logs.txt`
