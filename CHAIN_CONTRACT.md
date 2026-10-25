# Chain Contract: DNA Batch Parsing

## Overview
The DNA Batch Parsing chain reads raw DNA sequences from `data/raw/toSequence.txt`, parses each sequence against rule specifications, maintains execution idempotency via `data/processed_ledger.json`, writes cumulative output files (`toSequence_parsed.json` and `toSequence_parsed.csv`) atomically, and allows the caller/watcher to clear input upon successful completion.

---

## Contract Specification

### 1. Trigger
- **Manual/CLI Execution:** `python main.py --once` or executing `utils/dna_ui.py`.
- **Watcher Loop:** Background thread in `main.py` detecting non-empty changes in `data/raw/toSequence.txt`.

### 2. Inputs
- `input_path`: `data/raw/toSequence.txt` containing one DNA sequence string per line.
- `rules_folder`: Directory containing `rules_*.json` specification files (e.g., `rules/`).
- `ledger_path`: `data/processed_ledger.json` storing historical sequence processing state.

### 3. Terminal States
- **`SUCCESS`**: All new DNA sequences parsed or skipped via deduplication, cumulative outputs updated atomically, and ledger saved.
- **`WARN`**: Input file missing or empty (graceful early return).
- **`ERROR`**: Sequence-level rule parsing failure recorded in output/ledger as an error outcome (`error: <msg>`).
- **`CRITICAL_FAILURE`**: Unrecoverable rule loading error (`RuleLoadError`), input reading failure (`DNAProcessingError`), or atomic output persistence failure (`PersistenceError`).

### 4. Invariants
- **Idempotency:** Re-processing an already-recorded DNA sequence will never append duplicate entries to cumulative JSON/CSV output files.
- **Atomicity:** `toSequence_parsed.json` and `toSequence_parsed.csv` are updated together atomically via temporary files (`flush` + `fsync` + `os.replace`). Truncation of `toSequence.txt` occurs only after batch parsing succeeds.
- **Data Integrity:** In-memory state and disk files remain consistent; torn or partial writes are prevented.

### 5. Error Classes
- `DNAProcessingError`: Base exception for batch processing errors.
- `RuleLoadError`: Raised when loading JSON rule specifications fails.
- `PersistenceError`: Raised when writing temporary output files or performing atomic file replacements fails.

### 6. Idempotency Key
- `idempotency_key = dna_string` (e.g., `"VOL08900750712"`).

### 7. Atomicity Boundary
- Files written: `data/output/toSequence_parsed.json`, `data/output/toSequence_parsed.csv`, `data/processed_ledger.json`.
- Boundary enforcement: Write output to a temporary directory in the output filesystem, flush buffer, sync file descriptor (`fsync`), then atomically replace (`os.replace`) output files and save ledger.

### 8. Required Logs & Grep Recipes
- Start of sequence processing:
  `[Idempotency] key=<key> dedupe_hit=False terminal_outcome=processing`
- Deduplication skip:
  `[Idempotency] key=<key> dedupe_hit=True terminal_outcome=<outcome>`
- End of sequence processing:
  `[Idempotency] key=<key> dedupe_hit=False terminal_outcome=<outcome>`
- Batch summary:
  `[OK] Processed <count> new DNA strings. Total in ledger: <total>`

#### Grep Recipes:
```bash
# Filter deduplication hits
grep "dedupe_hit=True" logs.txt

# Filter idempotency status logs
grep "\[Idempotency\]" logs.txt
```
