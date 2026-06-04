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

def calculate_heat_gain(result):
    """
    Returns heat gain for a parsed result.
    'VOL' (Volume) sequences generate 0.3 heat (0.1 base + 0.2 penalty).
    Others generate 0.1 base heat.
    """
    base_gain = 0.1
    if result.get('rule') == 'Volume':
        return base_gain + 0.2
    return base_gain

def apply_thermal_noise(data):
    """
    Recursively scale numeric values by 0.9.
    Used when system_heat > NOISE_THRESHOLD.
    """
    if isinstance(data, dict):
        return {k: apply_thermal_noise(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [apply_thermal_noise(i) for i in data]
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        return data * 0.9
    else:
        return data

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
    """Raised when the system heat exceeds the safety threshold."""
    pass

# THERMAL CONSTANTS
MAX_HEAT = 10.0
NOISE_THRESHOLD = 7.0
COOLING_RATE = 0.0083  # ~1 unit every 2 minutes (0.008333... per second)

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
    return {"system_heat": 0.0, "last_update": time.time()}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main():
    # Determine file paths
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
        # Still process cooling if empty input
        state = load_system_state(state_path)
        now = time.time()
        elapsed = now - state["last_update"]
        old_heat = state["system_heat"]
        state["system_heat"] = max(0.0, old_heat - (COOLING_RATE * elapsed))
        state["last_update"] = now
        if state["system_heat"] != old_heat:
            save_system_state(state_path, state)
            print(f"[Thermal] INITIATE_COOLING_CYCLE heat={old_heat:.2f} -> {state['system_heat']:.2f}")
        return

    ledger = load_ledger(ledger_path)
    state = load_system_state(state_path)

    # Apply cooling
    now = time.time()
    elapsed = now - state["last_update"]
    old_heat = state["system_heat"]
    state["system_heat"] = max(0.0, old_heat - (COOLING_RATE * elapsed))
    state["last_update"] = now
    if state["system_heat"] < old_heat:
        print(f"[Thermal] INITIATE_COOLING_CYCLE heat={old_heat:.2f} -> {state['system_heat']:.2f}")

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
            # Pre-parse to check heat gain
            result = calculator.parse(dna_str)
            gain = calculate_heat_gain(result)

            if state["system_heat"] + gain > MAX_HEAT:
                print(f"[Thermal] SYSTEM_OVERHEAT_PROTECTION_ACTIVE heat={state['system_heat']:.2f} gain={gain:.2f} limit={MAX_HEAT}")
                state["system_heat"] += 0.05 # Stress from attempt
                save_system_state(state_path, state)
                raise ThermalOverloadError(f"System too hot ({state['system_heat']:.2f}). Refusing batch.")

            # Process with possible noise
            state["system_heat"] += gain
            parsed_values = result['values']
            if state["system_heat"] > NOISE_THRESHOLD:
                print(f"[Thermal] THERMAL_NOISE_APPLIED heat={state['system_heat']:.2f}")
                parsed_values = apply_thermal_noise(parsed_values)

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': parsed_values,
                'system_heat': round(state["system_heat"], 4)
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], parsed_values)
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except ThermalOverloadError as e:
            # Halt entire batch on overload
            print(f"[ERROR] Batch aborted: {e}")
            break

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

    if new_processed_count > 0 or state["system_heat"] < old_heat:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)

        with tempfile.TemporaryDirectory(dir=os.path.dirname(ledger_path)) as tmp_dir:
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
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

                # Save system state after successful commit
                save_system_state(state_path, state)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")
    else:
        print(f"[OK] Parsed {len(dna_list)} DNA strings. No new items to commit.")

if __name__ == '__main__':
    main()
