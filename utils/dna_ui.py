#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys for Thermal Fatigue System
UI_MESSAGES = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

# Thermal parameters
HEAT_PER_OPERATION = 2.0
MAX_HEAT_LIMIT = 10.0
HEAT_DECAY_RATE_PER_SEC = 0.5  # Dissipates 0.5 heat units per second

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
    """Raised when operational heat exceeds the core thermal limit."""
    def __init__(self, message, current_heat=None):
        super().__init__(message)
        self.message = message
        self.current_heat = current_heat
        self.consequence_applied = UI_MESSAGES["consequence_applied"]
        self.refusal_reason = UI_MESSAGES["refusal_reason"]
        self.next_action_hint = UI_MESSAGES["next_action_hint"]

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}
        except Exception:
            return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}
    return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}

def save_ledger(ledger_path, data):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def calculate_current_heat(system_state, now_dt=None):
    if now_dt is None:
        now_dt = datetime.datetime.now(datetime.timezone.utc)

    prev_heat = system_state.get('core_heat', 0.0)
    last_time_str = system_state.get('last_processed_timestamp')

    if not last_time_str:
        return prev_heat

    try:
        last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
        elapsed_seconds = max(0.0, (now_dt - last_dt).total_seconds())
        decay = elapsed_seconds * HEAT_DECAY_RATE_PER_SEC
        return max(0.0, prev_heat - decay)
    except Exception:
        return prev_heat

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
    if 'ledger' in ledger_data:
        ledger = ledger_data['ledger']
        system_state = ledger_data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})
    else:
        ledger = ledger_data
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    current_heat = calculate_current_heat(system_state, now_dt)

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
    initial_ledger = dict(ledger)

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Check Thermal Limit prior to processing operation
        if current_heat + HEAT_PER_OPERATION > MAX_HEAT_LIMIT:
            print(f"[System] {UI_MESSAGES['refusal_reason']}: Core heat={current_heat:.2f}. {UI_MESSAGES['next_action_hint']}")
            # Update and persist system thermal state even on refusal
            updated_state = {
                'ledger': initial_ledger,
                'system_state': {
                    'core_heat': current_heat,
                    'last_processed_timestamp': now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
                }
            }
            save_ledger(ledger_path, updated_state)
            raise ThermalOverloadError(
                f"Core heat limit exceeded ({current_heat + HEAT_PER_OPERATION:.1f}/{MAX_HEAT_LIMIT:.1f}). "
                f"{UI_MESSAGES['next_action_hint']}",
                current_heat=current_heat
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

        # Operation completed -> accumulate heat
        current_heat += HEAT_PER_OPERATION
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome} core_heat={current_heat:.2f}")
        new_processed_count += 1

    # Update system thermal state
    final_ledger_structure = {
        'ledger': ledger,
        'system_state': {
            'core_heat': current_heat,
            'last_processed_timestamp': now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
    }

    if new_processed_count > 0:
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

        # Save ledger
        save_ledger(ledger_path, final_ledger_structure)
    else:
        # Save cooling updates if timestamp elapsed
        save_ledger(ledger_path, final_ledger_structure)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Core Heat: {current_heat:.2f}/{MAX_HEAT_LIMIT:.2f}. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
