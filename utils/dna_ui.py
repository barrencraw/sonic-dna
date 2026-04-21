#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

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
    """Raised when system heat exceeds safety threshold."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if not os.path.isfile(input_path):
        return dna_list
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def load_system_state(state_path):
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"system_heat": 0.0}
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main(project_root=None):
    # Determine file paths
    if project_root is None:
        project_root = os.getcwd()

    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    rules_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {rules_folder}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        return

    ledger = load_ledger(ledger_path)
    system_state = load_system_state(state_path)
    system_heat = system_state.get("system_heat", 0.0)

    # Load existing outputs for merging
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
        except Exception:
            pass

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
    # Natural cooling: -1.0 per batch processing session (if non-empty)
    system_heat = max(0.0, system_heat - 1.0)

    for dna_str in dna_list:
        if dna_str in ledger:
            continue

        outcome = "success"
        try:
            result = calculator.parse(dna_str)
            rule_name = result['rule']
            vals = result['values']

            # --- Fatigue System Logic ---
            if rule_name == "Volume":
                amp = vals.get('amp', 0)
                heat_gain = amp / 100.0
                system_heat += heat_gain
                print(f"[THERMAL] Volume processing increased heat by {heat_gain:.2f}. Total: {system_heat:.2f}")

            elif rule_name == "Clarity":
                if system_heat > 10.0:
                    refusal = "[THERMAL_OVERLOAD] Heat exceeds safety threshold (10.0). Clarity processing suspended."
                    hint = "NEXT_ACTION_HINT: Cease high-amplitude operations. Allow system to reach thermal equilibrium."
                    print(f"{refusal} {hint}")
                    raise ThermalOverloadError(refusal)

                if system_heat > 0:
                    penalty = int(system_heat)
                    old_noise = vals['noise_floor']['value']
                    vals['noise_floor']['value'] = max(0, old_noise - penalty)
                    print(f"[THERMAL_STRESS] System heat at {system_heat:.2f}. Noise floor raised by {penalty}dB.")
            # ----------------------------

            entry = {
                'dna': dna_str,
                'rule': rule_name,
                'parsed': vals
            }
            parsed_json.append(entry)

            flat = flatten_parsed(rule_name, vals)
            flat['dna'] = dna_str
            flat['rule'] = rule_name
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        except (RuleParseError, ThermalOverloadError) as e:
            outcome = f"error: {str(e)}"
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        ledger[dna_str] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    # Atomic Save
    system_state["system_heat"] = system_heat
    save_system_state(state_path, system_state)

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger)

        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            with open(tmp_json, 'w', encoding='utf-8') as jf:
                json.dump(parsed_json, jf, indent=2)

            fieldnames = sorted(all_flattened_keys)
            with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                writer = csv.DictWriter(cf, fieldnames=fieldnames)
                writer.writeheader()
                for row in csv_rows:
                    writer.writerow({k: row.get(k, '') for k in fieldnames})

            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)

    print(f"[OK] Processed {new_processed_count} new DNA strings. System Heat: {system_heat:.2f}")

if __name__ == '__main__':
    main()
