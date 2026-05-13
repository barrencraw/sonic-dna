#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class TerminalOutcome(Enum):
    SUCCESS = "success"
    PARSE_ERROR = "error"
    SKIPPED = "skipped"

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
    """Raised when system heat exceeds threshold."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_list = []
    if not os.path.exists(input_path):
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

def apply_thermal_noise(values):
    """Recursively multiply all numeric values by 0.9."""
    if isinstance(values, dict):
        return {k: apply_thermal_noise(v) for k, v in values.items()}
    elif isinstance(values, (int, float)):
        return round(values * 0.9, 3)
    return values

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

def main():
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    ledger = load_ledger(ledger_path)
    state = load_system_state(state_path)

    # Passive dissipation
    state["system_heat"] = max(0.0, state["system_heat"] - 0.5)

    dna_list = read_input_file(input_file)
    # Even if dna_list is empty, we might want to save state if we dissipated heat.
    if not dna_list:
        save_system_state(state_path, state)
        return

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
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True")
                continue

            # Thermal Refusal Check
            if state["system_heat"] >= 10.0:
                print(f"[CONSEQUENCE] THERMAL_OVERLOAD: Heat at {state['system_heat']:.2f}/10.0. Refusing processing.")
                raise ThermalOverloadError(f"System heat too high: {state['system_heat']:.2f}")

            # Heat Accumulation
            heat_gain = 0.1 # Base

            try:
                result = calculator.parse(dna_str)
                outcome = TerminalOutcome.SUCCESS.value

                # Rule-specific heat
                if result['rule'] == 'Volume':
                    amp = result['values'].get('amp', 0)
                    heat_gain += (amp / 500.0)

                # Thermal Noise
                if state["system_heat"] > 5.0:
                    print(f"[CONSEQUENCE] THERMAL_DEGRADATION: Heat > 5.0 ({state['system_heat']:.2f}). Noise applied.")
                    result['values'] = apply_thermal_noise(result['values'])

                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

            except RuleParseError as e:
                outcome = TerminalOutcome.PARSE_ERROR.value
                parsed_json.append({'dna': dna_str, 'error': str(e)})
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

            # Commit to ledger
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            state["system_heat"] += heat_gain
            new_processed_count += 1
            print(f"[Processed] key={idempotency_key} outcome={outcome} heat={state['system_heat']:.2f}")

    finally:
        # Save state and ledger even on partial success or thermal error
        save_system_state(state_path, state)
        save_ledger(ledger_path, ledger)

        if new_processed_count > 0:
            # Atomic Write for JSON/CSV
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

            print(f"[OK] Processed {new_processed_count} new DNA strings.")

if __name__ == '__main__':
    main()
