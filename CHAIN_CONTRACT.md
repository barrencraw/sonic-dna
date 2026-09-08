# SonicDNA Chain Contract: DNA Batch Parsing

## 1. Overview & Chain Trigger
- **Chain Name:** DNA Batch Parsing
- **Trigger:** Watcher detection loop in `main.py` or single execution via `main.py --once` / direct call to `utils.dna_ui.main()`.
- **Primary Responsibility:** Reads DNA sequences from input file (`data/raw/toSequence.txt`), parses properties using `DNACalculator`, appends structured results to output formats (`data/output/toSequence_parsed.json` and `data/output/toSequence_parsed.csv`), updates the processed key ledger (`data/processed_ledger.json`), and clears the input file if parsing succeeds.

## 2. Inputs
- **Input File Path:** `data/raw/toSequence.txt`
- **Format:** Plain text, one DNA sequence string per line (e.g. `VOL08900750712`).
- **Rule Definitions:** `rules/rules_*.json` defining variables, prefixes, subvariables, and parsing boundaries.

## 3. Idempotency Key & Deduplication Strategy
- **Idempotency Key:** The DNA sequence string itself (e.g. `VOL08900750712`).
- **Ledger Storage:** `data/processed_ledger.json` maps each `idempotency_key` to its `terminal_outcome` (`success` or `error: <reason>`) and timestamp.
- **Behavior:**
  - If `idempotency_key` exists in ledger, skipping duplicate processing (`dedupe_hit=True`).
  - If `idempotency_key` is new, parse sequence, append to output arrays, and log (`dedupe_hit=False`).

## 4. Atomicity Boundary
- **Boundary:**
  1. Process all pending DNA sequences in batch.
  2. Write updated `toSequence_parsed.json` and `toSequence_parsed.csv` to a temporary directory in the output path.
  3. Flush and `os.fsync` temp file descriptors.
  4. Perform atomic replacement (`os.replace`) of the output JSON and CSV files.
  5. Save updated ledger (`data/processed_ledger.json`).
  6. Truncate/clear `data/raw/toSequence.txt` only after batch processing completes successfully without `PersistenceError` or critical runtime exceptions.

## 5. Terminal States
- **SUCCESS:** All new DNA sequences parsed or skipped via deduplication; atomic outputs committed; ledger saved; input file cleared.
- **FAILURE (HANDLED):** Parse errors on specific DNA strings record terminal outcome `error: <details>` in output files and ledger without interrupting batch for valid sequences.
- **CRITICAL FAILURE:** Persistence errors (e.g. disk full, permission denied on atomic write) raise `PersistenceError`. Input file `data/raw/toSequence.txt` is NOT cleared, allowing retry.

## 6. Error Taxonomy
- `DNAProcessingError` (Base class)
  - `RuleLoadError`: Rules folder missing or malformed rule files.
  - `PersistenceError`: IO failure during atomic temp file creation, sync, replace, or ledger write.
  - `RuleParseError`: Syntax/structure failure when parsing a specific DNA sequence.

## 7. Required Telemetry & Grep Recipes
- **Log Format:** `[Idempotency] key=<DNA_KEY> dedupe_hit=<True|False> terminal_outcome=<OUTCOME>`
- **Grep Recipes:**
  - Check deduplication hits:
    `grep "dedupe_hit=True" logs.log`
  - Check failed sequences:
    `grep "terminal_outcome=error" logs.log`
  - Monitor watcher cycle:
    `grep "\[Watcher\]" logs.log`
