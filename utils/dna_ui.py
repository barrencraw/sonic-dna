#!/usr/bin/env python3
import os
import json
import csv
import time
from utils.dna_calculator import DNACalculator, RuleParseError

MAX_HEAT = 10.0
COOLING_RATE = 0.0083  # units per second (~1 unit every 2 mins)
BASE_HEAT_GAIN = 0.1
VOL_HEAT_PENALTY = 0.2

MSG_CONSEQUENCE = "Thermal drift detected. Signal integrity compromised."
MSG_REFUSAL = "Hardware safety lockout. Core temperature exceeds 10.0 units."
MSG_HINT = "Passive cooling active. Await thermal equilibrium."

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

def flatten_parsed(rule_name, values_dict, parent_key=''):
    """
    Given nested values_dict, flatten into { 'rule.sub1.sub2': value, ... }.
    Useful for CSV.
    """
    items = {}
    for k, v in values_dict.items():
        new_key = f"{parent_key}.{k}" if parent_key else f"{rule_name}.{k}"
        if isinstance(v, dict):
            items.update(flatten_parsed(rule_name, v, new_key))
        else:
            items[new_key] = v
    return items

import tempfile
import shutil

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system heat exceeds MAX_HEAT."""
    pass

def apply_cooling(state):
    """
    Reduces system_heat based on elapsed time since last_processed_timestamp.
    """
    last_ts = state.get('last_processed_timestamp')
    if last_ts:
        elapsed = time.time() - last_ts
        cooling = elapsed * COOLING_RATE
        old_heat = state.get('system_heat', 0.0)
        state['system_heat'] = max(0.0, old_heat - cooling)
    return state

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Migration logic: if it's a flat dict, it's a legacy ledger
                if not isinstance(data, dict):
                    data = {}

                if "ledger" not in data:
                    # Legacy flat ledger: wrap it
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": os.path.getmtime(ledger_path),
                        "ledger": data
                    }
                return data
        except Exception:
            pass
    return {
        "system_heat": 0.0,
        "last_processed_timestamp": None,
        "ledger": {}
    }

def save_ledger(ledger_path, state):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    state = load_ledger(ledger_path)
    state = apply_cooling(state)
    ledger = state['ledger']

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
                else:
                    # Migration: dna -> dna_sequence
                    for entry in parsed_json:
                        if 'dna' in entry and 'dna_sequence' not in entry:
                            entry['dna_sequence'] = entry.pop('dna')
        except Exception:
            parsed_json = []

    # 2) Load existing CSV rows
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')
    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as cf:
                reader = csv.DictReader(cf)
                if reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    csv_rows = list(reader)
                    # Migration: dna -> dna_sequence
                    if 'dna' in all_flattened_keys:
                        all_flattened_keys.remove('dna')
                        all_flattened_keys.add('dna_sequence')
                    for row in csv_rows:
                        if 'dna' in row and 'dna_sequence' not in row:
                            row['dna_sequence'] = row.pop('dna')
        except Exception:
            pass

    from utils.dna_calculator import RuleParseError

    new_processed_count = 0
    old_heat = state['system_heat']

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            # Calculate heat gain
            gain = BASE_HEAT_GAIN
            if dna_str.startswith("VOL"):
                gain += VOL_HEAT_PENALTY

            if state['system_heat'] + gain > MAX_HEAT:
                print(f"[REFUSAL] {MSG_REFUSAL} Current heat: {state['system_heat']:.2f}, Gain: {gain:.2f}")
                print(f"[HINT] {MSG_HINT}")
                raise ThermalOverloadError(MSG_REFUSAL)

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            try:
                result = calculator.parse(dna_str)
                entry = {
                    'dna_sequence': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna_sequence'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna_sequence': dna_str,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna_sequence': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = f"error: {str(e)}"

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            state['system_heat'] += gain
            state['last_processed_timestamp'] = time.time()
            if state['system_heat'] > 5.0: # Arbitrary threshold for warning
                print(f"[CONSEQUENCE] {MSG_CONSEQUENCE} Heat: {state['system_heat']:.2f}")

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
            new_processed_count += 1
    except ThermalOverloadError:
        # Stop processing but proceed to save what we have
        pass

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')

        try:
            # 1) Write JSON output to temp
            with open(tmp_json, 'w', encoding='utf-8') as jf:
                json.dump(parsed_json, jf, indent=2)
                jf.flush()
                os.fsync(jf.fileno())

            # 2) Write CSV output to temp
            fieldnames = sorted(all_flattened_keys)
            with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                writer = csv.DictWriter(cf, fieldnames=fieldnames)
                writer.writeheader()
                for row in csv_rows:
                    out = {k: row.get(k, '') for k in fieldnames}
                    writer.writerow(out)
                cf.flush()
                os.fsync(cf.fileno())

            # 3) Atomic rename (commit)
            # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)

        except Exception as e:
            raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Parsed {len(dna_list)} DNA strings.")

    if new_processed_count > 0 or state['system_heat'] != old_heat:
        # Save ledger (state includes system_heat, last_processed_timestamp, and ledger)
        save_ledger(ledger_path, state)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
