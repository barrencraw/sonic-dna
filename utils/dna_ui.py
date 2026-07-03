#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Constants for Thermal Debt System ---
HEAT_PER_SEQUENCE = 5.0
DISSIPATION_RATE = 0.5
LOCKOUT_THRESHOLD = 100.0

UI_MESSAGES = {
    "HEAT_ACCUMULATED": "Heat Accumulation",
    "THERMAL_LOCKOUT": "Thermal Lockout",
    "HINT_DISSIPATION": "Dissipation required. System indifferent to urgency."
}

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
    """Raised when system heat exceeds lockout threshold."""
    pass

from enum import Enum
class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

def load_ledger(ledger_path):
    """
    Loads the ledger from disk.
    Standardizes format to: { "system_heat": 0.0, "last_processed_timestamp": 0, "ledger": {} }
    """
    default = {
        "system_heat": 0.0,
        "last_processed_timestamp": int(time.time()),
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # If it's the old flat format, migrate it
                if "ledger" not in data:
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": int(time.time()),
                        "ledger": data
                    }
                return data
        except Exception:
            return default
    return default

def save_ledger(ledger_path, ledger_data):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger_data, f, indent=2)

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
    ledger = ledger_data['ledger']
    current_heat = ledger_data.get('system_heat', 0.0)
    last_time = ledger_data.get('last_processed_timestamp', int(time.time()))

    # Calculate dissipation
    now = int(time.time())
    elapsed = max(0, now - last_time)
    dissipated = elapsed * DISSIPATION_RATE
    current_heat = max(0.0, current_heat - dissipated)

    print(f"[Thermal] Initial Heat: {current_heat:.1f} (Dissipated {dissipated:.1f} over {elapsed}s)")

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
    overload_occurred = False

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            entry = ledger[idempotency_key]
            if isinstance(entry, dict) and 'terminal_outcome' in entry:
                outcome = entry['terminal_outcome']
                # If it was refused, we allow retry. If success/error, we skip.
                if outcome != DNAStatus.REFUSED.value:
                    print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={outcome}")
                    continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            # Thermal Check
            if current_heat + HEAT_PER_SEQUENCE > LOCKOUT_THRESHOLD:
                print(f"[Thermal] {UI_MESSAGES['THERMAL_LOCKOUT']} (Heat: {current_heat:.1f}). {UI_MESSAGES['HINT_DISSIPATION']}")
                outcome = DNAStatus.REFUSED.value
                overload_occurred = True

                # Record refusal in ledger
                ledger[idempotency_key] = {
                    'terminal_outcome': outcome,
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
                }
                new_processed_count += 1
                break # Stop processing batch on lockout

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
            outcome = DNAStatus.SUCCESS.value
            current_heat += HEAT_PER_SEQUENCE
            print(f"[Thermal] {UI_MESSAGES['HEAT_ACCUMULATED']}: {current_heat:.1f}")

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
            outcome = DNAStatus.ERROR.value
            current_heat += HEAT_PER_SEQUENCE

        # Update ledger
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # Update ledger metadata
    ledger_data['system_heat'] = current_heat
    ledger_data['last_processed_timestamp'] = int(time.time())

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)

        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
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
                    json.dump(ledger_data, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")
    else:
        print(f"[OK] Parsed {len(dna_list)} DNA strings. No new items to process.")

    if overload_occurred:
        raise ThermalOverloadError(f"{UI_MESSAGES['THERMAL_LOCKOUT']} reached.")

if __name__ == '__main__':
    main()
