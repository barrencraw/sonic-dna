#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys for Thermal Stress
CONSEQUENCE_APPLIED = "THERMAL_NOISE_PENALTY"
REFUSAL_REASON = "THERMAL_OVERLOAD"
NEXT_ACTION_HINT = "ALLOW_SYSTEM_COOLING_BY_REDUCING_AMPLITUDE_OR_WAITING"

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
    """Raised when system heat prevents processing of high-clarity DNA."""
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
    if not os.path.exists(input_path):
        return []
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
    temp_dir = os.path.dirname(state_path)
    with tempfile.NamedTemporaryFile('w', dir=temp_dir, delete=False, encoding='utf-8') as tf:
        json.dump(state, tf, indent=2)
        temp_name = tf.name
    os.replace(temp_name, state_path)

def main(data_dir=None):
    # Determine file paths
    if data_dir:
        project_root = data_dir
    else:
        project_root = os.getcwd()

    data_folder = os.path.join(project_root, 'data')
    raw_folder = os.path.join(data_folder, 'raw')
    output_folder = os.path.join(data_folder, 'output')
    ledger_path = os.path.join(data_folder, 'processed_ledger.json')
    state_path = os.path.join(data_folder, 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    rules_path = os.path.join(project_root, 'rules')
    if not os.path.exists(rules_path):
        # Fallback for when running from project root but rules are in ./rules
        rules_path = 'rules'

    try:
        calculator = DNACalculator(rules_folder=rules_path)
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {rules_path}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
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

    new_processed_count = 0
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        outcome = "unknown"
        try:
            result = calculator.parse(dna_str)
            rule_name = result['rule']
            values = result['values']

            # --- SYSTEMIC RULE: FATIGUE (THERMAL STRESS) ---
            if rule_name == "Volume":
                amp = values.get('amp', 0)
                heat_gain = amp / 100.0
                system_heat += heat_gain
                print(f"[System] Rule=Volume amp={amp} heat_gain=+{heat_gain:.2f} total_heat={system_heat:.2f}")

            elif rule_name == "Clarity":
                if system_heat >= 10.0:
                    print(f"[System] Rule=Clarity REFUSAL: {REFUSAL_REASON} (heat={system_heat:.2f})")
                    raise ThermalOverloadError(f"{REFUSAL_REASON}: heat too high ({system_heat:.2f}). {NEXT_ACTION_HINT}")

                if system_heat > 0.0:
                    penalty = int(system_heat)
                    old_noise = values['noise_floor']['value']
                    # Penalty should make noise floor LOUDER.
                    # In CLA, higher value = quieter (e.g. 120 = -120dBFS, 0 = 0dBFS).
                    # So we decrease the value to increase the noise.
                    values['noise_floor']['value'] = max(0, old_noise - penalty)
                    print(f"[System] Rule=Clarity CONSEQUENCE: {CONSEQUENCE_APPLIED} penalty=-{penalty} noise_floor={old_noise}->{values['noise_floor']['value']}")

            entry = {
                'dna': dna_str,
                'rule': rule_name,
                'parsed': values
            }
            if rule_name == "Clarity" and system_heat > 0.0:
                entry['consequence'] = CONSEQUENCE_APPLIED

            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(rule_name, values)
            flat['dna'] = dna_str
            flat['rule'] = rule_name
            if rule_name == "Clarity" and system_heat > 0.0:
                flat['consequence'] = CONSEQUENCE_APPLIED

            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except ThermalOverloadError as e:
            outcome = f"error: {str(e)}"
            parsed_json.append({'dna': dna_str, 'error': str(e), 'refusal': REFUSAL_REASON})
            flat = {'dna': dna_str, 'error': str(e), 'refusal': REFUSAL_REASON}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        except RuleParseError as e:
            outcome = f"error: {str(e)}"
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count > 0:
        # Save ledger
        save_ledger(ledger_path, ledger)

        # Save system state
        system_state["system_heat"] = system_heat
        save_system_state(state_path, system_state)

        # ATOMIC WRITE PATTERN for outputs:
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

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     System Heat: {system_heat:.2f}")

if __name__ == '__main__':
    main()
