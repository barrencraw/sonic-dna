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
    """Raised when processing exceeds mainframe core heat threshold (Thermal Lockout)."""
    pass

# Systemic Pressure Axis: Thermal Fatigue Constants & Message Keys
MAX_CORE_HEAT = 10.0
HEAT_PER_SEQUENCE = 2.0
COOLING_RATE_PER_SEC = 0.5

# UI Message Keys for systemic feedback
MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

def load_ledger(ledger_path):
    """
    Loads processed ledger. Supports backward-compatible flat format as well
    as structured format with system_state.
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger_data):
    """
    Saves ledger atomically.
    """
    dir_name = os.path.dirname(ledger_path)
    ensure_folder(dir_name)
    with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
        json.dump(ledger_data, tf, indent=2)
        tf.flush()
        os.fsync(tf.fileno())
        temp_name = tf.name
    os.replace(temp_name, ledger_path)

def calculate_current_heat(last_heat: float, last_timestamp, current_timestamp=None) -> float:
    """
    Deterministically computes current core heat based on cooling dissipation over elapsed time.
    """
    if current_timestamp is None:
        current_timestamp = time.time()

    if last_timestamp is None:
        return 0.0

    try:
        if isinstance(last_timestamp, (int, float)):
            last_ts_epoch = float(last_timestamp)
        else:
            last_ts_epoch = time.mktime(time.strptime(str(last_timestamp), '%Y-%m-%d %H:%M:%S'))
    except Exception:
        last_ts_epoch = float(current_timestamp)

    elapsed = max(0.0, float(current_timestamp) - last_ts_epoch)
    cooled = max(0.0, float(last_heat) - (elapsed * COOLING_RATE_PER_SEC))
    return round(cooled, 4)

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

    raw_ledger_data = load_ledger(ledger_path)
    # Check if ledger data is formatted with 'system_state'
    if 'ledger' in raw_ledger_data and 'system_state' in raw_ledger_data:
        ledger = raw_ledger_data['ledger']
        system_state = raw_ledger_data['system_state']
    else:
        # Legacy flat structure or empty
        ledger = {k: v for k, v in raw_ledger_data.items() if k != 'system_state'}
        system_state = raw_ledger_data.get('system_state', {
            'core_heat': 0.0,
            'last_processed_timestamp': None
        })

    # Calculate current core heat after dissipation
    current_time_epoch = time.time()
    last_heat = float(system_state.get('core_heat', 0.0))
    last_ts = system_state.get('last_processed_timestamp')
    current_heat = calculate_current_heat(last_heat, last_ts, current_time_epoch)

    # 1) Load existing JSON output
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

        # Check Thermal Fatigue invariant BEFORE parsing/mutating
        if current_heat + HEAT_PER_SEQUENCE > MAX_CORE_HEAT:
            print(f"[Systemic Refusal] {MSG_REFUSAL_REASON}: core_heat={current_heat:.2f}/{MAX_CORE_HEAT:.2f}. {MSG_NEXT_ACTION_HINT}")
            # If any new items were already processed in this batch before lockout, commit them atomically
            if new_processed_count > 0:
                system_state['core_heat'] = current_heat
                system_state['last_processed_timestamp'] = current_time_epoch
                # Save ledger with updated system state and entries
                save_data = dict(ledger)
                save_data['ledger'] = ledger
                save_data['system_state'] = system_state

                with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                    tmp_json = os.path.join(tmp_dir, 'output.json')
                    tmp_csv = os.path.join(tmp_dir, 'output.csv')
                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())
                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)
                save_ledger(ledger_path, save_data)
            else:
                # Still record dissipated heat in ledger
                system_state['core_heat'] = current_heat
                system_state['last_processed_timestamp'] = current_time_epoch
                save_data = dict(ledger)
                save_data['ledger'] = ledger
                save_data['system_state'] = system_state
                save_ledger(ledger_path, save_data)

            raise ThermalOverloadError(
                f"{MSG_REFUSAL_REASON}: Core heat threshold ({MAX_CORE_HEAT}) exceeded with {current_heat + HEAT_PER_SEQUENCE:.2f}. {MSG_NEXT_ACTION_HINT}"
            )

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

        # Apply consequence: heat accumulation
        current_heat = round(current_heat + HEAT_PER_SEQUENCE, 4)
        print(f"[Systemic Consequence] {MSG_CONSEQUENCE_APPLIED}: core_heat={current_heat:.2f}/{MAX_CORE_HEAT:.2f}")

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # Update system state
    system_state['core_heat'] = current_heat
    system_state['last_processed_timestamp'] = current_time_epoch

    # Construct save data: maintain backward-compatibility with flat lookups while storing structured state
    save_data = dict(ledger)
    save_data['ledger'] = ledger
    save_data['system_state'] = system_state

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)
    # 4. Save ledger
    if new_processed_count > 0:
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

        # Save ledger
        save_ledger(ledger_path, save_data)
    elif last_heat != current_heat:
        # Save cooled thermal state even if no new sequences were processed
        save_ledger(ledger_path, save_data)

    print(f"[OK] Parsed {len(dna_list)} DNA strings.")
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}. Core heat: {current_heat:.2f}")
    if new_processed_count > 0:
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
