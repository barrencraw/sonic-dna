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
    """Raised when system heat exceeds the safety threshold."""
    pass

def load_system_state(state_path):
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"system_heat": 0.0}
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass

def apply_thermal_noise(val):
    if isinstance(val, dict):
        return {k: apply_thermal_noise(v) for k, v in val.items()}
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        # Apply a deterministic 0.9 penalty
        return val * 0.9
    return val

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

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    # Always load system state at start
    system_state = load_system_state(state_path)
    system_heat = system_state.get('system_heat', 0.0)

    try:
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

        ledger = load_ledger(ledger_path)

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
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            try:
                result = calculator.parse(dna_str)

                # Calculate heat gain
                gain = 0.0
                if result['rule'] == 'Volume':
                    amp = result['values'].get('amp', 0)
                    gain = 0.1 + (amp / 500.0)

                if system_heat + gain > 10.0:
                    print(f"[FATAL] Thermal Overload: {system_heat + gain:.2f} > 10.0")
                    print(f"[INFO] Dissipate heat via low-amplitude cycles...")
                    raise ThermalOverloadError(f"System overheat: {system_heat + gain:.2f}")

                values = result['values']
                if system_heat + gain > 5.0:
                    print(f"[SYSTEM] Thermal noise active: applying 0.9x penalty.")
                    values = apply_thermal_noise(values)

                system_heat += gain

                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': values,
                    'heat_at_processing': system_heat
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], values)
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                flat['system_heat'] = system_heat
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

        if new_processed_count > 0:
            save_ledger(ledger_path, ledger)

        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

    finally:
        # Passive dissipation
        system_heat = max(0.0, system_heat - 0.5)
        system_state['system_heat'] = system_heat
        save_system_state(state_path, system_state)

if __name__ == '__main__':
    main()
