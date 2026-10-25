#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
from utils.dna_calculator import DNACalculator, RuleParseError

# Standard UI Message Keys for Thermal Fatigue
MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

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
    """Raised when mainframe thermal limits are exceeded."""
    def __init__(self, message=MSG_REFUSAL_REASON):
        super().__init__(message)
        self.consequence_applied = MSG_CONSEQUENCE_APPLIED
        self.refusal_reason = MSG_REFUSAL_REASON
        self.next_action_hint = MSG_NEXT_ACTION_HINT

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
                if isinstance(data, dict):
                    return data
                return {}
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
    except Exception as e:
        raise PersistenceError(f"Failed to save ledger: {e}") from e

def run_batch(correlation_id=None):
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

    # Read DNA sequences
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    full_ledger_data = load_ledger(ledger_path)
    if 'ledger' in full_ledger_data and 'system_state' in full_ledger_data:
        ledger = full_ledger_data['ledger']
        system_state = full_ledger_data['system_state']
    else:
        ledger = full_ledger_data
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}

    initial_ledger = dict(ledger)

    # Heat dissipation calculation
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')

    if last_time_str:
        try:
            last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
        except Exception:
            try:
                last_dt = datetime.datetime.fromisoformat(last_time_str)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
            except Exception:
                last_dt = None

        if last_dt is not None:
            elapsed_seconds = (now_dt - last_dt).total_seconds()
            if elapsed_seconds > 0:
                dissipated = elapsed_seconds * 0.5
                core_heat = max(0.0, core_heat - dissipated)

    # Lockout check before starting sequence processing
    if core_heat >= 10.0:
        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = now_str
        save_ledger(ledger_path, {'ledger': initial_ledger, 'system_state': system_state})
        raise ThermalOverloadError(f"{MSG_REFUSAL_REASON}: Core heat at {core_heat:.1f}. {MSG_NEXT_ACTION_HINT}")

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
    refused = False

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', 'success')
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            continue

        if core_heat >= 10.0:
            refused = True
            break

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'dna_sequence': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['dna_sequence'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'dna_sequence': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1
        core_heat += 2.0
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        now_str = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

        if core_heat >= 10.0:
            refused = True
            break

    if refused:
        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = now_str
        save_ledger(ledger_path, {'ledger': initial_ledger, 'system_state': system_state})
        raise ThermalOverloadError(f"{MSG_REFUSAL_REASON}: Core heat reached {core_heat:.1f}. {MSG_NEXT_ACTION_HINT}")

    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = now_str

    if new_processed_count > 0:
        save_ledger(ledger_path, {'ledger': ledger, 'system_state': system_state})

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

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Core heat: {core_heat:.1f}")

main = run_batch

if __name__ == '__main__':
    main()
