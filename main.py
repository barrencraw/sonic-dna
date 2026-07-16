#!/usr/bin/env python3
"""
main.py

– If run directly (python main.py), this will launch your PySide6 GUI (ui/main_window.py),
  but also start a background watcher that “watches” data/raw/toSequence.txt. Any time
  you append new DNA lines to that file, it automatically:
     • calls dna_ui.run_batch() → which parses all lines and writes JSON/CSV to data/output/
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
from utils.dna_ui import run_batch, DNAProcessingError, ThermalOverloadError
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
        pass

def read_raw_contents(path: str) -> str:
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

            if current_content.strip() and current_content != last_content:
                timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                correlation_id = str(uuid.uuid4())
                print(f"[{timestamp}] New DNA detected (cid={correlation_id}) → running parser…")

                try:
                    run_batch(correlation_id=correlation_id)
                    clear_input_file(input_file)
                    print(f"[{timestamp}] Parsing complete. Cleared toSequence.txt.\n")
                except ThermalOverloadError as e:
                    print(f"[{timestamp}][Watcher][REFUSED] {e}. Input file NOT cleared.")
                except Exception as e:
                    if isinstance(e, DNAProcessingError):
                        print(f"[{timestamp}][Watcher][CRITICAL] DNA processing failed: {e}")
                    else:
                        print(f"[{timestamp}][Watcher][ERROR] Unexpected error: {e}")
                    # In case of other errors, we also DO NOT clear the input file

                last_content = ""
            else:
                if not current_content.strip():
                    last_content = ""

            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n[Watcher] Interrupted by user. Exiting watcher.")
        return

# ─── SINGLE‐RUN (NO GUI) MODE ──────────────────────────────────────────────────

def process_once():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    raw_folder = os.path.join(script_dir, 'data', 'raw')
    output_folder = os.path.join(script_dir, 'data', 'output')
    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        sys.exit(1)

    correlation_id = str(uuid.uuid4())
    print(f"[Once‐Runner] Processing all DNA strings (cid={correlation_id})…")
    try:
        run_batch(correlation_id=correlation_id)
        print("[Once‐Runner] Done.")
    except ThermalOverloadError as e:
        print(f"[Once‐Runner][REFUSED] {e}")
        # Not calling sys.exit(1) here as it's a systemic tradeoff, but maybe it should to signal caller
        sys.exit(1)
    except Exception as e:
        if isinstance(e, DNAProcessingError):
            print(f"[Once‐Runner][CRITICAL] DNA processing failed: {e}")
        else:
            print(f"[Once‐Runner][ERROR] Unexpected error: {e}")
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
    print("[main.py] Watcher thread started in background.")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    app = QApplication(sys.argv)
    rng = RngProvider()

    win = MainWindow(rng=rng)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
