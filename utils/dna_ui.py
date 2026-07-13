#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import datetime
from utils.dna_calculator import DNACalculator, RuleParseError

# Thermal Fatigue Constants
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0  # units per second

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
    """Raised when system heat exceeds safety limits."""
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

def get_utc_now():
    return datetime.datetime.now(datetime.timezone.utc)

def format_timestamp(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Backward compatibility
                if isinstance(data, dict) and "ledger" not in data:
                    return {
                        "system_heat": 0.0,
                        "last_update_timestamp": format_timestamp(get_utc_now()),
                        "ledger": data
                    }
                return data
        except Exception:
            pass
    return {
        "system_heat": 0.0,
        "last_update_timestamp": format_timestamp(get_utc_now()),
        "ledger": {}
    }

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
    ledger = state["ledger"]
    current_heat = state.get("system_heat", 0.0)
    last_time_str = state.get("last_update_timestamp")

    # Dissipate heat
    now = get_utc_now()
    if last_time_str:
        try:
            # Handle Z by replacing with +00:00 for older fromisoformat if needed
            last_time = datetime.datetime.fromisoformat(last_time_str.replace('Z', '+00:00'))
            elapsed = (now - last_time).total_seconds()
            dissipation = elapsed * COOLING_RATE
            current_heat = max(0.0, current_heat - dissipation)
        except ValueError:
            pass

    if not dna_list:
        # Just update heat dissipation and exit
        state["system_heat"] = current_heat
        state["last_update_timestamp"] = format_timestamp(now)
        save_ledger(ledger_path, state)
        return

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
    error_occurred = None

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            # Thermal Lockout Check
            if current_heat + HEAT_PER_SEQ > MAX_HEAT:
                print(f"[Error] Thermal Lockout: Critical heat levels detected ({current_heat:.1f}%). Operation refused.")
                print("Wait for dissipation. The system is indifferent to your deadlines.")
                raise ThermalOverloadError(f"Thermal Lockout at {current_heat:.1f}% heat")

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            outcome = "unknown"
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
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e)
                })
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "error"

            # Apply heat
            current_heat += HEAT_PER_SEQ
            print(f"[System] Heat Accumulation: +{HEAT_PER_SEQ} units. Current Level: {current_heat:.1f}%")

            # Update ledger
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': format_timestamp(get_utc_now())
            }
            new_processed_count += 1

    except ThermalOverloadError as e:
        error_occurred = e
    except Exception as e:
        error_occurred = e

    # Persist results
    # We always save if heat changed (dissipation) or new items processed or error occurred
    state["system_heat"] = current_heat
    state["last_update_timestamp"] = format_timestamp(get_utc_now())

    # Atomic write of output files and ledger
    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

        try:
            # 1) JSON
            with open(tmp_json, 'w', encoding='utf-8') as jf:
                json.dump(parsed_json, jf, indent=2)

            # 2) CSV
            if all_flattened_keys:
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)

            # 3) Ledger
            with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                json.dump(state, lf, indent=2)

            # Commit
            os.replace(tmp_json, json_output_path)
            if all_flattened_keys:
                os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)

        except Exception as e:
            if not error_occurred:
                raise PersistenceError("Failed to write output files atomically") from e
            else:
                print(f"[ERROR] Persistence failed during error handling: {e}")

    if error_occurred:
        raise error_occurred

    print(f"[OK] Processed {new_processed_count} new DNA strings. Heat: {current_heat:.1f}%")

if __name__ == '__main__':
    try:
        main()
    except DNAProcessingError as e:
        print(f"FATAL: {e}")
        exit(1)
