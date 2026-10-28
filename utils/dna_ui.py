#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# Systemic Thermal Fatigue Constants
HEAT_PER_SEQUENCE = 2.0
HEAT_LOCKOUT_THRESHOLD = 10.0
DISSIPATION_RATE = 0.5  # Heat units decayed per second

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
    """Raised when the thermal core exceeds lockout threshold."""
    def __init__(self, core_heat, threshold, message=None):
        self.core_heat = core_heat
        self.threshold = threshold
        self.consequence = "Heat Accumulation"
        self.refusal_reason = "Thermal Lockout"
        self.next_action_hint = "Wait for dissipation. The system is indifferent to your deadlines."
        msg = message or f"[Thermal Overload] Core heat {core_heat:.1f}/{threshold:.1f}. Refusal reason: {self.refusal_reason}. Hint: {self.next_action_hint}"
        super().__init__(msg)

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

def commit_outputs_and_ledger(output_folder, json_output_path, csv_output_path, ledger_path, parsed_json, csv_rows, all_flattened_keys, ledger):
    """Atomically writes JSON and CSV output files and saves the ledger."""
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

            # Save ledger before replacing files
            save_ledger(ledger_path, ledger)

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

    # Extract or initialize thermal system state
    system_state = ledger.get('_system_state', {})
    now_dt = datetime.datetime.now(datetime.timezone.utc)

    last_time_str = system_state.get('last_processed_timestamp')
    if last_time_str:
        try:
            last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (now_dt - last_dt).total_seconds())
        except Exception:
            elapsed_seconds = 0.0
    else:
        elapsed_seconds = 0.0

    raw_heat = float(system_state.get('core_heat', 0.0))
    current_heat = max(0.0, raw_heat - DISSIPATION_RATE * elapsed_seconds)

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
        if idempotency_key in ledger and idempotency_key != '_system_state':
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        # Check thermal fatigue lockout threshold before processing new item
        if current_heat >= HEAT_LOCKOUT_THRESHOLD:
            # Persist decayed state and commit any items processed so far in this batch before lockout
            ledger['_system_state'] = {
                'core_heat': current_heat,
                'last_processed_timestamp': now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            if new_processed_count > 0:
                commit_outputs_and_ledger(
                    output_folder, json_output_path, csv_output_path, ledger_path,
                    parsed_json, csv_rows, all_flattened_keys, ledger
                )
            else:
                save_ledger(ledger_path, ledger)
            raise ThermalOverloadError(current_heat, HEAT_LOCKOUT_THRESHOLD)

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

        # Accumulate heat for processed sequence
        current_heat += HEAT_PER_SEQUENCE
        print(f"[Thermal System] Consequence: Heat Accumulation | Core Heat: {current_heat:.1f}/{HEAT_LOCKOUT_THRESHOLD:.1f}")

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # Update final system state in ledger
    ledger['_system_state'] = {
        'core_heat': current_heat,
        'last_processed_timestamp': now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    }

    if new_processed_count > 0:
        commit_outputs_and_ledger(
            output_folder, json_output_path, csv_output_path, ledger_path,
            parsed_json, csv_rows, all_flattened_keys, ledger
        )
    else:
        # Save ledger even if no new sequences were processed to record thermal dissipation
        save_ledger(ledger_path, ledger)

    total_ledger_items = len([k for k in ledger if k != '_system_state'])
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {total_ledger_items}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
