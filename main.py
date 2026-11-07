#!/usr/bin/env python3
"""
main.py

– If run directly (python main.py), this will launch your PySide6 GUI (ui/main_window.py),
  but also start a background watcher that “watches” data/raw/toSequence.txt. Any time
  you append new DNA sequence lines to that file, it automatically:
     • calls dna_ui.main() → which parses all sequence lines and writes JSON/CSV to data/output/
     • clears toSequence.txt so those sequence lines aren’t re‐parsed

– If you want to run only a one‐time batch parse (no GUI), you can launch with
    python main.py --once
  and it will parse everything in toSequence.txt exactly once, write outputs, then exit.

Directory layout (relative to where this main.py lives):

  /your_project_root/
  ├─ main.py
  ├─ dna_calculator.py
  ├─ dna_ui.py
  ├─ ui/
  │   └─ main_window.py     ← your existing PySide6 window code
  ├─ rules/                 ← all your rule_*.json files
  └─ data/
      ├─ raw/
      │   └─ toSequence.txt ← add one DNA sequence string per line here
      └─ output/            ← results (toSequence_parsed.json + .csv) get written here
"""

import os
import sys
import time
import threading
import argparse
import uuid

# ─── Import the batch parser and the GUI window ───────────────────────────────
from utils.dna_ui import run_batch, DNAProcessingError, log_structured, DNAStatus
from utils.providers import RngProvider
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

# ─── UTILITY FUNCTIONS ────────────────────────────────────────────────────────

def ensure_folder(path: str):
    """Create the folder if it doesn’t exist."""
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def clear_input_file(path: str):
    """Truncate (empty) the file at `path`."""
    with open(path, 'w', encoding='utf-8'):
        pass  # opening in 'w' mode clears the file

def read_raw_contents(path: str) -> str:
    """
    Return the entire contents of the file at `path` as a string.
    If the file does not exist, returns an empty string.
    """
    if not os.path.isfile(path):
        return ""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

# ─── WATCHER LOOP ──────────────────────────────────────────────────────────────

def watch_loop():
    """
    Continuously watch data/raw/toSequence.txt. Whenever new non‐empty content appears,
    run the batch parser and then clear toSequence.txt. Sleeps 1 second between checks.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    raw_folder = os.path.join(script_dir, 'data', 'raw')
    output_folder = os.path.join(script_dir, 'data', 'output')
    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    last_content = ""

    log_structured("watcher_start", DNAStatus.SUCCESS.value, actor_id="watcher", outcome_detail="Monitoring data/raw/toSequence.txt")
    try:
        while True:
            current_content = read_raw_contents(input_file)

            # If there’s new non‐empty content that differs from last run, process it:
            if current_content.strip() and current_content != last_content:
                correlation_id = str(uuid.uuid4())
                log_structured("dna_detected", DNAStatus.SUCCESS.value, correlation_id=correlation_id, actor_id="watcher", outcome_detail="New DNA sequences detected")

                try:
                    run_batch(correlation_id=correlation_id)
                    clear_input_file(input_file)
                    log_structured("watcher_cleared", DNAStatus.SUCCESS.value, correlation_id=correlation_id, actor_id="watcher", outcome_detail="Cleared input sequence file after batch completion")
                except DNAProcessingError as e:
                    log_structured("watcher_error", DNAStatus.ERROR.value, correlation_id=correlation_id, actor_id="watcher", outcome_detail=f"DNA processing failed: {e}")
                except Exception as e:
                    log_structured("watcher_critical", DNAStatus.ERROR.value, correlation_id=correlation_id, actor_id="watcher", outcome_detail=f"Unexpected error: {e}")

                # Reset last_content so we’ll catch the next chunk of DNA sequences
                last_content = ""
            else:
                if not current_content.strip():
                    last_content = ""

            time.sleep(1.0)

    except KeyboardInterrupt:
        log_structured("watcher_stop", DNAStatus.SUCCESS.value, actor_id="watcher", outcome_detail="Interrupted by user. Exiting watcher.")
        return

# ─── SINGLE‐RUN (NO GUI) MODE ──────────────────────────────────────────────────

def process_once():
    """
    Run the batch parser exactly once (reads all sequence lines from toSequence.txt,
    writes output JSON+CSV, then exits).
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    raw_folder = os.path.join(script_dir, 'data', 'raw')
    output_folder = os.path.join(script_dir, 'data', 'output')
    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured("process_once", DNAStatus.REFUSED.value, actor_id="once_runner", outcome_detail=f"Input file not found: {input_file}")
        return

    correlation_id = str(uuid.uuid4())
    log_structured("process_once_start", DNAStatus.SUCCESS.value, correlation_id=correlation_id, actor_id="once_runner", outcome_detail="Processing all DNA sequences once")
    try:
        run_batch(correlation_id=correlation_id)
        log_structured("process_once_complete", DNAStatus.SUCCESS.value, correlation_id=correlation_id, actor_id="once_runner", outcome_detail="Done")
    except DNAProcessingError as e:
        log_structured("process_once_error", DNAStatus.ERROR.value, correlation_id=correlation_id, actor_id="once_runner", outcome_detail=f"DNA processing failed: {e}")
        sys.exit(1)
    except Exception as e:
        log_structured("process_once_critical", DNAStatus.ERROR.value, correlation_id=correlation_id, actor_id="once_runner", outcome_detail=f"Unexpected error: {e}")
        sys.exit(1)

# ─── MAIN ENTRYPOINT ───────────────────────────────────────────────────────────

def main():
    """
    Parse command‐line args:
      • If '--once' is provided, run process_once() and exit.
      • Otherwise (default), start the watcher in a background thread and launch the GUI.
    """
    parser = argparse.ArgumentParser(description="DNA‐Parser + GUI Launcher")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the DNA batch parser exactly once (no GUI, no watcher)."
    )
    args = parser.parse_args()

    if args.once:
        process_once()
        return

    watcher_thread = threading.Thread(target=watch_loop, daemon=True)
    watcher_thread.start()
    log_structured("app_start", DNAStatus.SUCCESS.value, actor_id="main", outcome_detail="Watcher thread started in background")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    app = QApplication(sys.argv)

    rng = RngProvider()

    win = MainWindow(rng=rng)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
