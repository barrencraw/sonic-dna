#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
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
    """Raised when the system exceeds MAX_HEAT."""
    pass

# Thermal Fatigue Constants
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0  # units per second

def load_ledger(ledger_path):
    """
    Loads ledger and system state. Supports legacy flat format.
    """
    state = {
        'system_heat': 0.0,
        'last_processed_timestamp': None,
        'ledger': {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'ledger' in data:
                    state.update(data)
                elif isinstance(data, dict):
                    # Backward compatibility for flat ledger
                    state['ledger'] = data
        except Exception:
            pass
    return state

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

    state = load_ledger(ledger_path)
    ledger = state['ledger']
    current_heat = float(state.get('system_heat', 0.0))
    last_time = state.get('last_processed_timestamp')

    now = time.time()
    if last_time:
        try:
            elapsed = now - float(last_time)
            dissipated = elapsed * COOLING_RATE
            if dissipated > 0:
                current_heat = max(0.0, current_heat - dissipated)
                print(f"[Heat Dissipation] dissipated={dissipated:.1f} current_heat={current_heat:.1f}")
        except (ValueError, TypeError):
            pass

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")

    skip_processing = not dna_list

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

    new_processed_count = 0
    error_to_raise = None

    try:
        if not skip_processing:
            for dna_str in dna_list:
                idempotency_key = dna_str
                if idempotency_key in ledger:
                    print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                    continue

                # Thermal Lockout check
                if current_heat + HEAT_PER_SEQ > MAX_HEAT:
                    print(f"[Thermal Lockout] heat={current_heat:.1f} refuse_key={idempotency_key}")
                    print("Wait for dissipation. The system is indifferent to your deadlines.")
                    error_to_raise = ThermalOverloadError("Thermal Lockout")
                    break

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

                # Heat Accumulation
                current_heat += HEAT_PER_SEQ
                print(f"[Heat Accumulation] key={idempotency_key} heat={current_heat:.1f}")

                ledger[idempotency_key] = {
                    'terminal_outcome': outcome,
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
                }
                new_processed_count += 1

    except Exception as e:
        error_to_raise = e

    # Update state for persistence
    state['system_heat'] = current_heat
    state['last_processed_timestamp'] = time.time()

    # ATOMIC WRITE PATTERN for outputs and ledger
    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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

            # 3) Write Ledger to temp
            with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                json.dump(state, lf, indent=2)
                lf.flush()
                os.fsync(lf.fileno())

            # 4) Atomic renames (commit)
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)

        except Exception as e:
            if not error_to_raise:
                error_to_raise = PersistenceError("Failed to write output files atomically")
            else:
                print(f"[CRITICAL] Persistence failed after previous error: {e}")

    if error_to_raise:
        raise error_to_raise

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON -> {json_output_path}")
    print(f"     CSV  -> {csv_output_path}")

if __name__ == '__main__':
    main()
