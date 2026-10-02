# Mini Chain Contract: DNA Batch Processing

## Trigger
- File modification detected in `data/raw/toSequence.txt` by watcher loop in `main.py`.
- Manual/CLI invocation via `python main.py --once` or direct call to `utils.dna_ui.run_batch()`.

## Inputs
- `data/raw/toSequence.txt`: Raw DNA sequences (one per line).
- Rule JSON files in `rules/`: Modular variable parsing specifications.
- `data/processed_ledger.json`: Persistent ledger tracking processed DNA sequences and terminal outcomes.
- `data/output/toSequence_parsed.json` and `.csv`: Cumulative parsed output datasets.

## Terminal States
- `success`: DNA sequence parsed successfully according to active rule schema.
- `error: <message>`: DNA sequence failed rule parsing (`RuleParseError`); recorded in ledger and cumulative dataset.
- `skipped`: DNA sequence key found in ledger; skipped without re-computation or duplicate output entry.

## Invariants
1. **Atomicity:** All file persistence operations (JSON output, CSV output, and processed ledger) commit atomically using temporary files, flushing, fsyncing, and replacing files. Partial or torn writes are strictly prevented.
2. **Idempotency:** A DNA sequence present in `data/processed_ledger.json` is never re-parsed or duplicated in cumulative output files.
3. **Queue Draining:** `data/raw/toSequence.txt` is truncated/cleared if and only if `run_batch()` completes without unhandled persistence errors.

## Error Classes
- `DNAProcessingError`: Base class for DNA pipeline errors.
- `RuleLoadError`: Raised when rules in `rules/` cannot be loaded or initialized.
- `PersistenceError`: Raised when writing temporary files or atomic file renaming (`os.replace`) fails.

## Idempotency Key Strategy
- **Key:** The raw DNA sequence string (e.g., `VOL08900750712`).
- **Store:** `data/processed_ledger.json`.

## Atomicity Boundary
1. Prepare output structures (`parsed_json`, `csv_rows`, `ledger`).
2. Write temporary files (`tmp_json`, `tmp_csv`, `tmp_ledger`) within a temporary directory located inside `data/output/` (same filesystem to ensure atomic rename).
3. Call `.flush()` and `os.fsync()` on file descriptors before closing.
4. Execute `os.replace()` to atomically swap temporary files with destination files (`toSequence_parsed.json`, `toSequence_parsed.csv`, `processed_ledger.json`).

## Telemetry & Log Format
- `[Watcher] New DNA detected → running parser…`
- `[Idempotency] key=<dna_sequence> dedupe_hit=<True|False> terminal_outcome=<outcome>`
- `[OK] Processed <count> new DNA strings. Total in ledger: <total>`

## Grep Recipes
- Check deduplication hits:
  ```bash
  grep "\[Idempotency\]" log.txt | grep "dedupe_hit=True"
  ```
- Check terminal outcomes:
  ```bash
  grep "\[Idempotency\]" log.txt | grep "terminal_outcome="
  ```
