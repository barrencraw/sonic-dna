#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError
from utils.integrity import IntegrityManager

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if os.path.exists(input_path):
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

def main():
    # Determine file paths
    project_root = os.getcwd()
    data_folder = os.path.join(project_root, 'data')
    raw_folder = os.path.join(data_folder, 'raw')
    output_folder = os.path.join(data_folder, 'output')
    ledger_path = os.path.join(data_folder, 'processed_ledger.json')
    integrity_path = os.path.join(data_folder, 'system_integrity.json')
    messages_path = os.path.join(data_folder, 'system_messages.json')

    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        # If no input file, just return silently or with a small log
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Instantiate Integrity Manager
    integrity_mgr = IntegrityManager(integrity_path, messages_path)

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        return

    ledger = load_ledger(ledger_path)

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
            result = calculator.parse(dna_str)

            # Check integrity
            if not integrity_mgr.can_process(result):
                print(f"[REFUSAL] {integrity_mgr.get_message('refusal_reason')}")
                print(f"[HINT] {integrity_mgr.get_message('next_action_hint')}")
                # We skip this DNA - it won't be in the ledger, so it can be retried later
                continue

            # Apply Wear
            change = integrity_mgr.apply_wear(result)
            print(f"[CONSEQUENCE] {integrity_mgr.get_message('consequence_applied', change=change, integrity=integrity_mgr.integrity)}")

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
            # On parse error, we still apply normal wear
            change = integrity_mgr.apply_wear({'rule': 'unknown'})
            print(f"[CONSEQUENCE] Error processing DNA. {integrity_mgr.get_message('consequence_applied', change=change, integrity=integrity_mgr.integrity)}")

            # Record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        # Record in ledger
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
        with tempfile.TemporaryDirectory(dir=data_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'toSequence_parsed.json')
            tmp_csv = os.path.join(tmp_dir, 'toSequence_parsed.csv')
            tmp_ledger = os.path.join(tmp_dir, 'processed_ledger.json')

            try:
                # 1) Write JSON
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) Write CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Write Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Save Integrity
                integrity_mgr.save_integrity(tmp_dir=tmp_dir)

                # 5) Atomic renames
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                # Integrity is already replaced by save_integrity if tmp_dir is passed

            except Exception as e:
                raise PersistenceError(f"Failed to write output files atomically: {e}") from e

        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     Integrity: {integrity_mgr.integrity}")

if __name__ == '__main__':
    main()
