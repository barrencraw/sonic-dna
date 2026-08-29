#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys (Legibility Pass)
CONSEQUENCE_HEAT_ACCUMULATION = "Heat Accumulation"
REFUSAL_THERMAL_LOCKOUT = "Thermal Lockout"
HINT_WAIT_FOR_DISSIPATION = "Wait for dissipation. The system is indifferent to your deadlines."

# Thermal Fatigue Parameters
HEAT_PER_SEQUENCE = 2.0
MAX_HEAT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5

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
    """Raised when processing accumulates core heat exceeding safety lockout threshold."""
    def __init__(self, current_heat=MAX_HEAT_THRESHOLD, threshold=MAX_HEAT_THRESHOLD,
                 message_key=REFUSAL_THERMAL_LOCKOUT, hint=HINT_WAIT_FOR_DISSIPATION):
        self.current_heat = current_heat
        self.threshold = threshold
        self.message_key = message_key
        self.hint = hint
        super().__init__(f"[{message_key}] Core heat {current_heat:.1f}/{threshold:.1f}. {hint}")

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

def _commit_outputs(output_folder, json_output_path, csv_output_path, parsed_json, csv_rows, all_flattened_keys):
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

    ledger = load_ledger(ledger_path)

    # 1) Thermal state calculation & decay
    system_state = ledger.get('_system_state', {})
    current_heat = float(system_state.get('core_heat', 0.0))
    last_time = float(system_state.get('last_processed_timestamp', time.time()))
    now = time.time()

    elapsed = max(0.0, now - last_time)
    current_heat = max(0.0, current_heat - (elapsed * COOLING_RATE_PER_SEC))

    if current_heat >= MAX_HEAT_THRESHOLD:
        ledger['_system_state'] = {
            'core_heat': current_heat,
            'last_processed_timestamp': now
        }
        save_ledger(ledger_path, ledger)
        print(f"[{REFUSAL_THERMAL_LOCKOUT}] Core heat {current_heat:.1f}/{MAX_HEAT_THRESHOLD:.1f}. {HINT_WAIT_FOR_DISSIPATION}")
        raise ThermalOverloadError(current_heat, MAX_HEAT_THRESHOLD)

    # 2) Load existing JSON output
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

    # 3) Load existing CSV rows
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

        # Check thermal capacity before processing new sequence
        if current_heat + HEAT_PER_SEQUENCE > MAX_HEAT_THRESHOLD:
            ledger['_system_state'] = {
                'core_heat': current_heat,
                'last_processed_timestamp': time.time()
            }
            if new_processed_count > 0:
                _commit_outputs(output_folder, json_output_path, csv_output_path, parsed_json, csv_rows, all_flattened_keys)
                save_ledger(ledger_path, ledger)
            print(f"[{REFUSAL_THERMAL_LOCKOUT}] Core heat overload on sequence '{dna_str}'. {HINT_WAIT_FOR_DISSIPATION}")
            raise ThermalOverloadError(current_heat, MAX_HEAT_THRESHOLD)

        current_heat += HEAT_PER_SEQUENCE
        print(f"[{CONSEQUENCE_HEAT_ACCUMULATION}] sequence={dna_str} +{HEAT_PER_SEQUENCE:.1f} heat → core_heat={current_heat:.1f}/{MAX_HEAT_THRESHOLD:.1f}")

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

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    ledger['_system_state'] = {
        'core_heat': current_heat,
        'last_processed_timestamp': time.time()
    }

    if new_processed_count > 0:
        _commit_outputs(output_folder, json_output_path, csv_output_path, parsed_json, csv_rows, all_flattened_keys)

    save_ledger(ledger_path, ledger)

    real_ledger_count = len([k for k in ledger if k != '_system_state'])
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {real_ledger_count}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
