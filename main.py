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
from utils.dna_ui import main as run_batch, DNAProcessingError, ThermalOverloadError
from utils.providers import RngProvider

try:
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    HAS_PYSIDE = True
except ImportError:
    HAS_PYSIDE = False

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
    # Avoid chdir if possible, use absolute paths
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
                    run_batch(correlation_id=correlation_id, actor_id="watcher")
                    clear_input_file(input_file)
                    print(f"[{timestamp}] Parsing complete. Cleared toSequence.txt.\n")
                except ThermalOverloadError as e:
                    print(f"[{timestamp}][Watcher][WARNING] Thermal overload: {e}. Input file NOT cleared.")
                except DNAProcessingError as e:
                    print(f"[{timestamp}][Watcher][CRITICAL] DNA processing failed: {e}")
                except Exception as e:
                    print(f"[{timestamp}][Watcher][ERROR] Unexpected error: {e}")

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
    """
    Run the batch parser exactly once (reads all lines from toSequence.txt,
    writes output JSON+CSV, then exits).
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    raw_folder = os.path.join(script_dir, 'data', 'raw')
    ensure_folder(raw_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    correlation_id = str(uuid.uuid4())
    print(f"[Once‐Runner] Processing all DNA strings (cid={correlation_id}) once…")
    try:
        run_batch(correlation_id=correlation_id, actor_id="once-runner")
        print("[Once‐Runner] Done.")
    except Exception as e:
        if isinstance(e, DNAProcessingError):
            print(f"[Once‐Runner][CRITICAL] DNA processing failed: {e}")
        else:
            print(f"[Once‐Runner][ERROR] Unexpected error: {e}")
        sys.exit(1)

# ─── MAIN ENTRYPOINT ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DNA‐Parser + GUI Launcher")
    parser.add_argument("--once", action="store_true", help="Run the DNA batch parser exactly once.")
    args = parser.parse_args()

    if args.once:
        process_once()
        return

    # Background thread for watching files
    watcher_thread = threading.Thread(target=watch_loop, daemon=True)
    watcher_thread.start()
    print("[main.py] Watcher thread started in background.")

    if HAS_PYSIDE:
        app = QApplication(sys.argv)
        rng = RngProvider()
        win = MainWindow(rng=rng)
        win.show()
        sys.exit(app.exec())
    else:
        print("[main.py] PySide6 not found. Running in headless mode.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[main.py] Headless mode interrupted.")

if __name__ == "__main__":
    main()
