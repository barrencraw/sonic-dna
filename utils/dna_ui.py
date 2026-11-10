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
    """Raised when processing exceeds the mainframe thermal capacity."""
    pass

# Thermal Fatigue Constants
HEAT_PER_PARSE = 2.0
LOCKOUT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5

# Legibility Pass: UI Message Keys
MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

def calculate_current_heat(stored_heat, last_timestamp, now_timestamp):
    """
    Deterministically computes mainframe core heat after passive dissipation.
    """
    if last_timestamp is None:
        return 0.0
    elapsed = max(0.0, now_timestamp - last_timestamp)
    dissipated = elapsed * COOLING_RATE_PER_SEC
    return max(0.0, stored_heat - dissipated)

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    system_state = data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})
                    # Items can be in data['ledger'] or at the root (excluding 'system_state' and 'ledger')
                    ledger_items = dict(data.get('ledger', {}))
                    for k, v in data.items():
                        if k not in ('ledger', 'system_state'):
                            ledger_items[k] = v
                    return {
                        'ledger': ledger_items,
                        'system_state': system_state
                    }
                return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}
        except Exception:
            return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}
    return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}

def save_ledger(ledger_path, ledger_data):
    # To maintain full backward compatibility with any tests checking `dna in ledger` directly on the loaded json dict,
    # we export ledger keys at root as well as under 'ledger' and 'system_state'.
    out = dict(ledger_data.get('ledger', {}))
    out['ledger'] = ledger_data.get('ledger', {})
    out['system_state'] = ledger_data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
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
        return

    ledger_data = load_ledger(ledger_path)
    ledger_items = ledger_data.get('ledger', {})
    system_state = ledger_data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})

    now_ts = time.time()
    current_heat = calculate_current_heat(
        system_state.get('core_heat', 0.0),
        system_state.get('last_processed_timestamp'),
        now_ts
    )

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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger_items:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger_items[idempotency_key]['terminal_outcome']}")
            continue

        # Check Thermal Lockout threshold before processing new sequence
        if current_heat + HEAT_PER_PARSE > LOCKOUT_THRESHOLD:
            # Consequence / Refusal triggered
            system_state['core_heat'] = current_heat
            system_state['last_processed_timestamp'] = now_ts
            save_ledger(ledger_path, {'ledger': ledger_items, 'system_state': system_state})

            print(f"[{MSG_REFUSAL_REASON}] Current Core Heat: {current_heat:.2f}/{LOCKOUT_THRESHOLD:.2f}.")
            print(f"[{MSG_NEXT_ACTION_HINT}]")
            raise ThermalOverloadError(
                f"{MSG_REFUSAL_REASON}: Current heat {current_heat:.2f} exceeds tolerance for additional processing ({HEAT_PER_PARSE} units). {MSG_NEXT_ACTION_HINT}"
            )

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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

        current_heat += HEAT_PER_PARSE
        print(f"[{MSG_CONSEQUENCE_APPLIED}] Sequence parsed: +{HEAT_PER_PARSE} heat -> Current Core Heat: {current_heat:.2f}")

        ledger_items[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    print(f"[OK] Parsed {len(dna_list)} DNA strings.")

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)
        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

        # Update system thermal state and save ledger after output files successfully commit
        system_state['core_heat'] = current_heat
        system_state['last_processed_timestamp'] = now_ts
        save_ledger(ledger_path, {'ledger': ledger_items, 'system_state': system_state})

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger_items)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
