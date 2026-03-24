#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from utils.dna_calculator import DNACalculator, RuleParseError
from utils.integrity_manager import IntegrityManager

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
        return []
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

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Load system messages
    system_messages = {}
    if os.path.exists(messages_path):
        with open(messages_path, 'r', encoding='utf-8') as f:
            system_messages = json.load(f)

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Initialize Integrity Manager
    integrity_manager = IntegrityManager(integrity_path)

    # Read DNA strings
    dna_list = read_input_file(input_file)
    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
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
            rule_name = result['rule']
            values = result['values']

            # Check for refusal
            if integrity_manager.is_refused(rule_name, values):
                outcome = "refusal"
                entry = {
                    'dna': dna_str,
                    'outcome': outcome,
                    'reason': system_messages.get('refusal_reason'),
                    'hint': system_messages.get('next_action_hint')
                }
                parsed_json.append(entry)
                flat = {'dna': dna_str, 'outcome': outcome, 'error': system_messages.get('refusal_reason')}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
            else:
                # Process normally
                wear = integrity_manager.calculate_wear(rule_name, values)
                integrity_manager.apply_wear(wear)

                outcome = "success"
                entry = {
                    'dna': dna_str,
                    'rule': rule_name,
                    'parsed': values,
                    'outcome': outcome,
                    'system_msg': system_messages.get('consequence_applied'),
                    'integrity_after': integrity_manager.integrity
                }
                parsed_json.append(entry)

                flat = flatten_parsed(rule_name, values)
                flat['dna'] = dna_str
                flat['rule'] = rule_name
                flat['outcome'] = outcome
                flat['integrity_after'] = integrity_manager.integrity
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

        except RuleParseError as e:
            outcome = f"error: {str(e)}"
            parsed_json.append({
                'dna': dna_str,
                'outcome': 'error',
                'error': str(e)
            })
            flat = {'dna': dna_str, 'outcome': 'error', 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        # Update ledger
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
        with tempfile.TemporaryDirectory(dir=data_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_integrity = os.path.join(tmp_dir, 'integrity.json')

            try:
                # 1) JSON
                with open(tmp_json, 'w', encoding='utf-8') as f:
                    json.dump(parsed_json, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                # 2) CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    f.flush()
                    os.fsync(f.fileno())

                # 3) Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as f:
                    json.dump(ledger, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                # 4) Integrity
                with open(tmp_integrity, 'w', encoding='utf-8') as f:
                    json.dump(integrity_manager.get_state(), f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic renames
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_integrity, integrity_path)

            except Exception as e:
                raise PersistenceError(f"Failed to write output files atomically: {e}") from e

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     Integrity: {integrity_manager.integrity}")

if __name__ == '__main__':
    main()
