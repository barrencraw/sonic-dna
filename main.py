#!/usr/bin/env python3
"""
main.py

– If run directly (python main.py), this will launch your PySide6 GUI (ui/main_window.py),
  but also start a background watcher that “watches” data/raw/toSequence.txt. Any time
  you append new DNA lines to that file, it automatically:
     • calls dna_ui.main() → which parses all lines and writes JSON/CSV to data/output/
     • clears toSequence.txt so those lines aren’t re‐parsed

– If you want to run only a one‐time batch parse (no GUI), you can launch with
    python main.py --once
  and it will parse everything in toSequence.txt exactly once, write outputs, then exit.
"""

import os
import sys
import time
import threading
import argparse
import uuid

# ─── Import the batch parser and the GUI window ───────────────────────────────
from utils.dna_ui import main as run_batch, log_structured, DNAStatus, DNAProcessingError, ensure_folder
from utils.providers import RngProvider
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

# ─── UTILITY FUNCTIONS ────────────────────────────────────────────────────────

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

    log_structured("system", "watcher_init", DNAStatus.SUCCESS.value, extra={"message": "Watcher Started. Monitoring data/raw/toSequence.txt"})
    try:
        while True:
            current_content = read_raw_contents(input_file)

            if current_content.strip() and current_content != last_content:
                correlation_id = str(uuid.uuid4())
                log_structured(correlation_id, "watcher_detection", DNAStatus.SUCCESS.value, extra={"message": "New DNA detected"})

                try:
                    run_batch(correlation_id=correlation_id)
                    clear_input_file(input_file)
                    log_structured(correlation_id, "watcher_cleanup", DNAStatus.SUCCESS.value, extra={"message": "Cleared toSequence.txt"})
                except Exception as e:
                    outcome = DNAStatus.ERROR.value
                    log_structured(correlation_id, "watcher_processing", outcome, extra={"error": str(e)})

                last_content = ""
            else:
                if not current_content.strip():
                    last_content = ""

            time.sleep(1.0)

    except KeyboardInterrupt:
        return

# ─── SINGLE‐RUN (NO GUI) MODE ──────────────────────────────────────────────────

def process_once():
    """
    Run the batch parser exactly once.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    raw_folder = os.path.join(script_dir, 'data', 'raw')
    output_folder = os.path.join(script_dir, 'data', 'output')
    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    correlation_id = str(uuid.uuid4())
    log_structured(correlation_id, "once_runner_start", DNAStatus.SUCCESS.value)

    try:
        run_batch(correlation_id=correlation_id)
        log_structured(correlation_id, "once_runner_finish", DNAStatus.SUCCESS.value)
    except Exception as e:
        log_structured(correlation_id, "once_runner_failure", DNAStatus.ERROR.value, extra={"error": str(e)})
        sys.exit(1)

# ─── MAIN ENTRYPOINT ───────────────────────────────────────────────────────────

def main():
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

    app = QApplication(sys.argv)
    rng = RngProvider()
    win = MainWindow(rng=rng)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
