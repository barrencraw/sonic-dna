#!/usr/bin/env python3
import os
import json
import csv
import time
from utils.dna_calculator import DNACalculator, RuleParseError

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

MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE_PER_SEC = 0.01

MSG_CONSEQUENCE = "System thermal load increased. Efficiency nominal."
MSG_REFUSAL = "System thermal overload detected. Batch processing refused to prevent hardware fatigue."
MSG_HINT = "Wait for system cooling or reduce batch size."

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
    """Raised when the system heat exceeds MAX_HEAT."""
    pass

def load_ledger(ledger_path):
    """
    Returns a dict: {
       'system_heat': float,
       'last_processed_timestamp': float,
       'ledger': { key: {terminal_outcome, timestamp} }
    }
    """
    default_state = {
        'system_heat': 0.0,
        'last_processed_timestamp': time.time(),
        'ledger': {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Migration for legacy ledger format (plain dict)
                if 'ledger' not in data:
                    return {
                        'system_heat': 0.0,
                        'last_processed_timestamp': time.time(),
                        'ledger': data
                    }
                return data
        except Exception:
            return default_state
    return default_state

def save_ledger(ledger_path, full_state):
    ledger_dir = os.path.dirname(ledger_path)
    ensure_folder(ledger_dir)
    with tempfile.TemporaryDirectory(dir=ledger_dir) as tmp_dir:
        tmp_path = os.path.join(tmp_dir, 'ledger.json')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(full_state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)

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

    full_state = load_ledger(ledger_path)
    ledger = full_state['ledger']

    # Thermal Fatigue Logic
    now = time.time()
    elapsed = now - full_state['last_processed_timestamp']
    cooling = elapsed * COOLING_RATE_PER_SEC
    current_heat = max(0.0, full_state['system_heat'] - cooling)

    # Count how many are actually NEW
    items_to_process = [d for d in dna_list if d not in ledger]
    if not items_to_process:
        print("[Idempotency] All items in batch already processed. Skipping logic.")
        # We still might want to update the heat/timestamp even if skipping?
        # Usually only on attempt. But here we already cooled it.
        full_state['system_heat'] = current_heat
        full_state['last_processed_timestamp'] = now
        save_ledger(ledger_path, full_state)
        return

    predicted_heat = current_heat + (len(items_to_process) * HEAT_PER_ITEM)
    if predicted_heat > MAX_HEAT:
        print(f"[REFUSAL] {MSG_REFUSAL}")
        print(f"[HINT] {MSG_HINT}")
        # Save cooled heat before raising
        full_state['system_heat'] = current_heat
        full_state['last_processed_timestamp'] = now
        save_ledger(ledger_path, full_state)
        raise ThermalOverloadError(MSG_REFUSAL)

    print(f"[Heat] Current: {current_heat:.2f}, Predicted: {predicted_heat:.2f}, Max: {MAX_HEAT}")

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
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
        except Exception:
            pass

    from utils.dna_calculator import RuleParseError

    new_processed_count = 0
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
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
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)

        except Exception as e:
            raise PersistenceError("Failed to write output files atomically") from e

    # Finalize state
    full_state['system_heat'] = predicted_heat
    full_state['last_processed_timestamp'] = now
    save_ledger(ledger_path, full_state)

    print(f"[OK] {MSG_CONSEQUENCE}")
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
