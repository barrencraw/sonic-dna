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
    """Raised when system heat prevents processing."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
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
                return json.load(f).get('system_heat', 0.0)
        except Exception:
            return 0.0
    return 0.0

def save_system_state(state_path, heat):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump({'system_heat': heat}, f, indent=2)

def main():
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(os.path.join(project_root, 'data'))
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
    system_heat = load_system_state(state_path)

    # Natural cooling: -1.0 per batch if non-empty
    system_heat = max(0.0, system_heat - 1.0)

    # We save system state if the list was non-empty, even if everything is deduplicated
    # because cooling happened.
    save_system_state(state_path, system_heat)

    # Load existing outputs to append
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as f:
                parsed_json = json.load(f)
        except Exception: pass

    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')
    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                all_flattened_keys = set(reader.fieldnames)
                csv_rows = list(reader)
        except Exception: pass

    new_processed_count = 0
    for dna_str in dna_list:
        if dna_str in ledger:
            continue

        try:
            result = calculator.parse(dna_str)
            rule_name = result['rule']
            values = result['values']

            # Fatigue System Logic
            if rule_name == 'Volume':
                amp = values.get('amp', 0)
                heat_gain = amp / 100.0
                system_heat += heat_gain
                print(f"[CONSEQUENCE_APPLIED] Thermal stress increased by {heat_gain:.2f}. Current heat: {system_heat:.2f}")
                # Save heat gain immediately in case of subsequent refusal in same batch
                save_system_state(state_path, system_heat)

            elif rule_name == 'Clarity':
                if system_heat > 10.0:
                    print(f"[REFUSAL_REASON] Thermal overload ({system_heat:.2f}). Clarity extraction aborted.")
                    print(f"[NEXT_ACTION_HINT] Allow system to cool or process lower-amplitude strings.")
                    raise ThermalOverloadError(f"Heat {system_heat:.2f} exceeds threshold 10.0")

                if system_heat > 0.0:
                    # Apply penalties
                    penalty_noise = int(system_heat)
                    penalty_thd = int(system_heat * 10)

                    # Clarity: noise_floor (sign 'N', value), thd (int)
                    if 'noise_floor' in values:
                        values['noise_floor']['value'] = max(0, values['noise_floor']['value'] - penalty_noise)
                    if 'thd' in values:
                        values['thd'] = min(1000, values['thd'] + penalty_thd)

                    print(f"[CONSEQUENCE_APPLIED] Thermal noise penalty applied due to system heat ({system_heat:.2f}).")

            entry = {'dna': dna_str, 'rule': rule_name, 'parsed': values}
            parsed_json.append(entry)
            flat = flatten_parsed(rule_name, values)
            flat['dna'] = dna_str
            flat['rule'] = rule_name
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except ThermalOverloadError as e:
            outcome = f"error: {str(e)}"
            parsed_json.append({'dna': dna_str, 'error': outcome})
            csv_rows.append({'dna': dna_str, 'error': outcome})
            all_flattened_keys.update(['dna', 'error'])
        except RuleParseError as e:
            outcome = f"error: {str(e)}"
            parsed_json.append({'dna': dna_str, 'error': outcome})
            csv_rows.append({'dna': dna_str, 'error': outcome})
            all_flattened_keys.update(['dna', 'error'])

        ledger[dna_str] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    # Atomic Write of main outputs
    if new_processed_count > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'out.json')
            tmp_csv = os.path.join(tmp_dir, 'out.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                with open(tmp_json, 'w', encoding='utf-8') as f:
                    json.dump(parsed_json, f, indent=2)

                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        writer.writerow({k: row.get(k, '') for k in fieldnames})

                with open(tmp_ledger, 'w', encoding='utf-8') as f:
                    json.dump(ledger, f, indent=2)

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                # Final save of system state
                save_system_state(state_path, system_heat)

            except Exception as e:
                raise PersistenceError(f"Atomic write failed: {e}")

    print(f"[OK] Processed {new_processed_count} new DNA strings. System heat: {system_heat:.2f}")

if __name__ == '__main__':
    main()
