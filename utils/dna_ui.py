#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

# Systemic Message Keys for Thermal Fatigue / System Overheat
UI_MESSAGES = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

# Thermal fatigue constants
HEAT_PER_SEQUENCE = 2.0
LOCKOUT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5

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
    """Raised when mainframe temperature exceeds safety lockout threshold."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'ledger' in data:
                    return data
                elif isinstance(data, dict):
                    return {
                        'ledger': data,
                        'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}
                    }
        except Exception:
            return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}
    return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}

def save_ledger(ledger_path, ledger_data):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger_data, f, indent=2)

def calculate_current_heat(core_heat, last_timestamp_str, current_time):
    if not last_timestamp_str:
        return 0.0
    try:
        last_time = datetime.strptime(last_timestamp_str, '%Y-%m-%dT%H:%M:%SZ')
        elapsed_sec = (current_time - last_time).total_seconds()
        if elapsed_sec < 0:
            elapsed_sec = 0
        dissipated = elapsed_sec * COOLING_RATE_PER_SEC
        return max(0.0, core_heat - dissipated)
    except Exception:
        return core_heat

def commit_batch_outputs(output_folder, parsed_json, csv_rows, all_flattened_keys, ledger_path, ledger_data):
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')

        try:
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

        except Exception as e:
            raise PersistenceError("Failed to write output files atomically") from e

    save_ledger(ledger_path, ledger_data)

def main():
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data.get('ledger', {})
    system_state = ledger_data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    current_heat = calculate_current_heat(
        system_state.get('core_heat', 0.0),
        system_state.get('last_processed_timestamp'),
        now
    )

    if current_heat >= LOCKOUT_THRESHOLD:
        print(f"[{UI_MESSAGES['refusal_reason']}] Current Heat: {current_heat:.1f}/{LOCKOUT_THRESHOLD}. {UI_MESSAGES['next_action_hint']}")
        raise ThermalOverloadError(f"{UI_MESSAGES['refusal_reason']}: Core temperature ({current_heat:.1f}) exceeds threshold ({LOCKOUT_THRESHOLD}). {UI_MESSAGES['next_action_hint']}")

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
    lockout_occurred = False

    for dna_seq in dna_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        if current_heat >= LOCKOUT_THRESHOLD:
            print(f"[{UI_MESSAGES['refusal_reason']}] Dynamic limit hit during batch processing. {UI_MESSAGES['next_action_hint']}")
            lockout_occurred = True
            break

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_seq)
            entry = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_seq
            flat['dna_sequence'] = dna_seq
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "error"

        current_heat += HEAT_PER_SEQUENCE
        now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        system_state['core_heat'] = current_heat
        system_state['last_processed_timestamp'] = now_str
        new_processed_count += 1
        print(f"[{UI_MESSAGES['consequence_applied']}] key={idempotency_key} added {HEAT_PER_SEQUENCE} heat. Current heat={current_heat:.1f}")

    if new_processed_count > 0:
        ledger_data['ledger'] = ledger
        ledger_data['system_state'] = system_state
        commit_batch_outputs(output_folder, parsed_json, csv_rows, all_flattened_keys, ledger_path, ledger_data)

    if lockout_occurred:
        raise ThermalOverloadError(f"{UI_MESSAGES['refusal_reason']}: Dynamic lockout threshold hit at {current_heat:.1f} heat. {UI_MESSAGES['next_action_hint']}")

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
