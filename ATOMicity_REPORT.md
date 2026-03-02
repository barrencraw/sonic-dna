# Atomicity Boundary Report

## Chain 1: DNA Batch Parsing
**Location:** `main.py` (Watcher/Once-Runner) and `utils/dna_ui.py` (Parser Logic)

### Steps that must be atomic
1. Read `data/raw/toSequence.txt`
2. Parse DNA strings
3. Write `data/output/toSequence_parsed.json`
4. Write `data/output/toSequence_parsed.csv`
5. Clear `data/raw/toSequence.txt`

### Current State
- **Transactions:** None.
- **Partial Success Scenarios:**
    - JSON written, CSV fails.
    - JSON and CSV written, but input file not cleared (results in re-processing).
    - Partial/Torn writes to JSON or CSV if crash occurs during I/O.
- **Corruption/Bad States:**
    - Malformed JSON/CSV (truncated files).
    - Inconsistency between JSON and CSV.
    - Infinite re-processing loop if watcher is running and input isn't cleared.

### Proposed Solution
Implement an **Atomic Write + Commit** pattern:
1. Write JSON and CSV to a temporary directory.
2. Once both are fully written and flushed, rename them to their final destinations (Atomic Rename).
3. Only after both renames succeed, truncate `data/raw/toSequence.txt`.

---

## Chain 2: Audio Download
**Location:** `ui/music_panel.py`

### Steps that must be atomic
1. Generate/Normalize audio data.
2. Write WAV file.

### Current State
- **Partial Success Scenarios:** Crash during WAV write results in a corrupt/unplayable file.
- **Corruption/Bad States:** Truncated WAV file.

### Proposed Solution
While less critical than the batch parser, using a temp file + rename for the WAV export would ensure we never leave a half-written file.

---

## Selected Chain for Implementation
**Chain 1: DNA Batch Parsing** is the most critical as it involves multiple files and a "queue" (`toSequence.txt`) that must be drained correctly to avoid duplication and inconsistency.
