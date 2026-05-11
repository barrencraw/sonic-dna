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

SYSTEMIC_MESSAGES = {
    "CONSEQUENCE_APPLIED": "Thermal accumulation detected. Signal fidelity compromised.",
    "REFUSAL_REASON": "Safety protocol: Thermal threshold exceeded. Operations halted.",
    "NEXT_ACTION_HINT": "Await dissipation or reduce amplitude in future sequences."
}

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

def main(data_dir=None):
    # Determine file paths
    project_root = os.getcwd()
    if data_dir is None:
        data_dir = os.path.join(project_root, 'data')

    raw_folder = os.path.join(data_dir, 'raw')
    output_folder = os.path.join(data_dir, 'output')
    ledger_path = os.path.join(data_dir, 'processed_ledger.json')
    state_path = os.path.join(data_dir, 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        # Fallback for tests or other environments where rules might be in a different place
        try:
            calculator = DNACalculator(rules_folder=os.path.join(os.path.dirname(project_root), 'rules'))
        except:
            raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        # Passive dissipation even if no DNA
        system_state = load_system_state(state_path)
        system_heat = max(0.0, system_state.get("system_heat", 0.0) - 0.5)
        system_state['system_heat'] = round(system_heat, 2)
        save_system_state(state_path, system_state)
        print("[WARN] No DNA strings found in toSequence.txt. Dissipated heat.")
        return

    ledger = load_ledger(ledger_path)
    system_state = load_system_state(state_path)
    system_heat = system_state.get("system_heat", 0.0)

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
    any_new_work = False
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if system_heat > 10.0:
            print(f"[REFUSAL] {SYSTEMIC_MESSAGES['REFUSAL_REASON']} {SYSTEMIC_MESSAGES['NEXT_ACTION_HINT']}")
            # DO NOT update ledger for refused strings so they can be retried later
            continue

        try:
            result = calculator.parse(dna_str)

            # Apply Fatigue rules
            if result['rule'] == 'Volume':
                amp = result['values'].get('amp', 0)
                heat_gain = amp / 100.0
                system_heat += heat_gain
                print(f"[CONSEQUENCE] Volume processing. Heat +{heat_gain:.2f}. Total Heat: {system_heat:.2f}")

            if result['rule'] == 'Clarity':
                if system_heat > 0:
                    old_thd = result['values'].get('thd', 0)
                    penalty = int(system_heat) * 10
                    new_thd = min(1000, old_thd + penalty)
                    result['values']['thd'] = new_thd

                    nf_data = result['values'].get('noise_floor', {'sign': 'N', 'value': 90})
                    old_nf = nf_data['value']
                    new_nf = max(0, old_nf - int(system_heat))
                    result['values']['noise_floor']['value'] = new_nf

                    print(f"[CONSEQUENCE] {SYSTEMIC_MESSAGES['CONSEQUENCE_APPLIED']} Clarity penalized. THD {old_thd}->{new_thd}, NF {old_nf}->{new_nf}")

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
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        # Update ledger and count INSIDE loop for successfully processed or parsed-error strings
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1
        any_new_work = True

    # Passive dissipation at the end of batch
    system_heat = max(0.0, system_heat - 0.5)
    system_state['system_heat'] = round(system_heat, 2)

    if any_new_work:
        # ATOMIC WRITE PATTERN for outputs
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            try:
                # 1) Write JSON
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) Write CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Commit
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

        # Save ledger
        save_ledger(ledger_path, ledger)

    # Always save system state to persist dissipation
    save_system_state(state_path, system_state)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     Heat level: {system_heat:.2f}")
    if any_new_work:
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
