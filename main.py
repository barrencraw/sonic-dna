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
      │   └─ toSequence.txt ← add one DNA string per line here
      └─ output/            ← results (toSequence_parsed.json + .csv) get written here
"""

import os
import sys
import time
import threading
import argparse
import uuid

# ─── Import the batch parser and the GUI window ───────────────────────────────
from utils.dna_ui import run_batch
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

    print("[Watcher] Started. Monitoring data/raw/toSequence.txt for new DNA lines…")
    try:
        while True:
            current_content = read_raw_contents(input_file)

            # If there’s new non‐empty content that differs from last run, process it:
            if current_content.strip() and current_content != last_content:
                timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                print(f"[{timestamp}] New DNA detected → running parser…")

                correlation_id = str(uuid.uuid4())
                try:
                    run_batch(correlation_id=correlation_id, actor_id='batch_parser')
                    # Only clear the input file if run_batch() succeeds
                    clear_input_file(input_file)
                    print(f"[{timestamp}] Parsing complete. Cleared toSequence.txt.\n")
                except Exception as e:
                    # Classify errors
                    from utils.dna_ui import DNAProcessingError
                    if isinstance(e, DNAProcessingError):
                        print(f"[{timestamp}][Watcher][CRITICAL] DNA processing failed: {e}")
                    else:
                        print(f"[{timestamp}][Watcher][ERROR] Unexpected error: {e}")
                    # In case of error, we DO NOT clear the input file so we can retry or investigate

                # Reset last_content so we’ll catch the next chunk of DNA
                last_content = ""
            else:
                # If the file is now empty, keep last_content = ""
                if not current_content.strip():
                    last_content = ""

            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n[Watcher] Interrupted by user. Exiting watcher.")
        return

# ─── SINGLE‐RUN (NO GUI) MODE ──────────────────────────────────────────────────

def process_once():
    """
    Run the batch parser exactly once (reads all lines from toSequence.txt,
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
        print(f"[ERROR] Input file not found: {input_file}")
        return

    print("[Once‐Runner] Processing all DNA strings once…")
    correlation_id = str(uuid.uuid4())
    try:
        run_batch(correlation_id=correlation_id, actor_id='batch_parser')
        print("[Once‐Runner] Done.")
    except Exception as e:
        from utils.dna_ui import DNAProcessingError
        if isinstance(e, DNAProcessingError):
            print(f"[Once‐Runner][CRITICAL] DNA processing failed: {e}")
        else:
            print(f"[Once‐Runner][ERROR] Unexpected error: {e}")
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
        # Run batch a single time, then exit
        process_once()
        return

    # Otherwise: start watcher, then launch GUI
    watcher_thread = threading.Thread(target=watch_loop, daemon=True)
    watcher_thread.start()
    print("[main.py] Watcher thread started in background.")

    # Launch PySide6 GUI
    # Ensure working directory is project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    app = QApplication(sys.argv)

    # Initialize Determinism Providers
    rng = RngProvider()  # Default non-deterministic for normal usage, or seed if needed

    win = MainWindow(rng=rng)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
