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
    """Raised when the system is too hot to process more DNA."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

def flatten_parsed(rule_name, values_dict, parent_key=''):
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
            pass
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def apply_thermal_noise(values):
    """Recursively multiply all numeric values by 0.9."""
    if isinstance(values, dict):
        return {k: apply_thermal_noise(v) for k, v in values.items()}
    elif isinstance(values, (int, float)) and not isinstance(values, bool):
        return values * 0.9
    return values

def main():
    project_root = os.getcwd()
    data_folder = os.path.join(project_root, 'data')
    raw_folder = os.path.join(data_folder, 'raw')
    output_folder = os.path.join(data_folder, 'output')
    ledger_path = os.path.join(data_folder, 'processed_ledger.json')
    state_path = os.path.join(data_folder, 'system_state.json')

    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules: {e}")

    dna_list = read_input_file(input_file)
    if not dna_list:
        return

    ledger = load_ledger(ledger_path)
    system_state = load_system_state(state_path)

    # Passive Cooling
    system_state['system_heat'] = max(0.0, system_state['system_heat'] - 1.0)

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
    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            # Calculate heat gain
            heat_gain = 0.2
            try:
                # Preview parse to see if it's Volume
                if dna_str.startswith("VOL"):
                    # We need the amp. VOL0890... -> 890
                    amp_str = dna_str[3:7]
                    if amp_str.isdigit():
                        amp = int(amp_str)
                        if amp < 100:
                            heat_gain = -0.5 # Cooling cycle
                        else:
                            heat_gain = 0.1 + (amp / 500.0)
            except Exception:
                pass

            if system_state['system_heat'] + heat_gain > 10.0:
                print(f"[FATAL] Thermal Overload. Cooling required. Heat: {system_state['system_heat']:.2f}")
                raise ThermalOverloadError(f"Thermal Overload: {system_state['system_heat'] + heat_gain:.2f}")

            outcome = "success"
            noise_active = False
            if system_state['system_heat'] + heat_gain > 5.0:
                noise_active = True
                print(f"[SYSTEM] Thermal noise active. Precision loss detected. Heat: {system_state['system_heat'] + heat_gain:.2f}")

            try:
                result = calculator.parse(dna_str)
                values = result['values']
                if noise_active:
                    values = apply_thermal_noise(values)

                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': values,
                    'thermal_noise': noise_active
                }
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], values)
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                flat['thermal_noise'] = noise_active
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

            except RuleParseError as e:
                outcome = f"error: {str(e)}"
                parsed_json.append({'dna': dna_str, 'error': str(e)})
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

            system_state['system_heat'] = max(0.0, system_state['system_heat'] + heat_gain)
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")

    finally:
        # Save state even if we crashed or finished
        save_system_state(state_path, system_state)

        if new_processed_count > 0:
            # ATOMIC WRITE
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

            save_ledger(ledger_path, ledger)
            print(f"[OK] Processed {new_processed_count} new DNA strings.")

if __name__ == '__main__':
    main()
