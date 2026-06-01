#!/usr/bin/env python3
"""
main.py
"""

import os
import sys
import time
import threading
import argparse
import uuid

# ─── Import the batch parser and the GUI window ───────────────────────────────
from utils.dna_ui import main as run_batch
from utils.providers import RngProvider
try:
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

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

def watch_loop(base_dir=None):
    """
    Continuously watch data/raw/toSequence.txt. Whenever new non‐empty content appears,
    run the batch parser and then clear toSequence.txt. Sleeps 1 second between checks.
    """
    if base_dir is None:
        base_dir = os.getcwd()

    raw_folder = os.path.join(base_dir, 'data', 'raw')
    output_folder = os.path.join(base_dir, 'data', 'output')
    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    last_content = ""

    print(f"[Watcher] Started. Monitoring {input_file} for new DNA lines…")
    try:
        while True:
            current_content = read_raw_contents(input_file)

            # If there’s new non‐empty content that differs from last run, process it:
            if current_content.strip() and current_content != last_content:
                timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                correlation_id = str(uuid.uuid4())
                print(f"[{timestamp}][{correlation_id}] New DNA detected → running parser…")

                try:
                    run_batch(correlation_id=correlation_id, base_dir=base_dir)
                    # Only clear the input file if run_batch() succeeds
                    clear_input_file(input_file)
                    print(f"[{timestamp}][{correlation_id}] Parsing complete. Cleared toSequence.txt.\n")
                except Exception as e:
                    # Classify errors
                    from utils.dna_ui import DNAProcessingError
                    if isinstance(e, DNAProcessingError):
                        print(f"[{timestamp}][{correlation_id}][Watcher][CRITICAL] DNA processing failed: {e}")
                    else:
                        print(f"[{timestamp}][{correlation_id}][Watcher][ERROR] Unexpected error: {e}")
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

def process_once(base_dir=None):
    """
    Run the batch parser exactly once (reads all lines from toSequence.txt,
    writes output JSON+CSV, then exits).
    """
    if base_dir is None:
        base_dir = os.getcwd()

    raw_folder = os.path.join(base_dir, 'data', 'raw')
    output_folder = os.path.join(base_dir, 'data', 'output')
    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    print(f"[Once‐Runner] Processing all DNA strings from {input_file} once…")
    correlation_id = str(uuid.uuid4())
    try:
        run_batch(correlation_id=correlation_id, base_dir=base_dir)
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

    # Ensure working directory is script directory for normal usage
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if args.once:
        # Run batch a single time, then exit
        process_once(base_dir=script_dir)
        return

    # Otherwise: start watcher, then launch GUI
    watcher_thread = threading.Thread(target=watch_loop, args=(script_dir,), daemon=True)
    watcher_thread.start()
    print("[main.py] Watcher thread started in background.")

    if not HAS_GUI:
        print("[main.py] GUI dependencies (PySide6) not found. Watcher is running. Press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)

    app = QApplication(sys.argv)

    # Initialize Determinism Providers
    rng = RngProvider()  # Default non-deterministic for normal usage, or seed if needed

    win = MainWindow(rng=rng)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
