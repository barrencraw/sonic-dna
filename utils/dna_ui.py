#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

def flatten_parsed(rule_name, values_dict, parent_key=''):
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
                return json.load(f)
        except Exception:
            return {}
    return {}

def main(correlation_id="unknown", actor_id="unknown"):
    """
    Main entry point for DNA batch processing.
    Implements the Observability Contract and Atomic Write Pattern.
    """
    print(f"[OBSERVABILITY] correlation_id={correlation_id} actor_id={actor_id} step=start outcome=processing")

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[OBSERVABILITY] correlation_id={correlation_id} actor_id={actor_id} step=terminal outcome=ERROR error='Input file not found'")
        return

    # 1. Load Rules
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        print(f"[OBSERVABILITY] correlation_id={correlation_id} actor_id={actor_id} step=terminal outcome=ERROR error='Rule load failure'")
        raise RuleLoadError(f"Could not load rules: {e}")

    # 2. Read DNA Strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        print(f"[OBSERVABILITY] correlation_id={correlation_id} actor_id={actor_id} step=terminal outcome=ERROR error='Input read failure'")
        raise DNAProcessingError(f"Failed to read input file: {e}")

    if not dna_list:
        print(f"[OBSERVABILITY] correlation_id={correlation_id} actor_id={actor_id} step=terminal outcome=NO_NEW_DATA")
        return

    # 3. Load State
    ledger = load_ledger(ledger_path)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list): parsed_json = []
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

    # 4. Process Loop
    new_processed_count = 0
    for dna_str in dna_list:
        if dna_str in ledger:
            print(f"[OBSERVABILITY] correlation_id={correlation_id} actor_id={actor_id} step=process_dna idempotency_key={dna_str} outcome=DEDUPE")
            continue

        print(f"[OBSERVABILITY] correlation_id={correlation_id} actor_id={actor_id} step=process_dna idempotency_key={dna_str} outcome=processing")

        try:
            result = calculator.parse(dna_str)
            entry = {'dna': dna_str, 'rule': result['rule'], 'parsed': result['values']}
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "SUCCESS"
        except RuleParseError as e:
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "ERROR"

        ledger[dna_str] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    # 5. Atomic Persistence
    if new_processed_count > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'out.json')
            tmp_csv = os.path.join(tmp_dir, 'out.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                # Write JSON
                with open(tmp_json, 'w', encoding='utf-8') as f:
                    json.dump(parsed_json, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                # Write CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        writer.writerow({k: row.get(k, '') for k in fieldnames})
                    f.flush()
                    os.fsync(f.fileno())

                # Write Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as f:
                    json.dump(ledger, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic swap
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
            except Exception as e:
                print(f"[OBSERVABILITY] correlation_id={correlation_id} actor_id={actor_id} step=terminal outcome=ERROR error='Persistence failed'")
                raise PersistenceError(f"Atomic commit failed: {e}")

    print(f"[OBSERVABILITY] correlation_id={correlation_id} actor_id={actor_id} step=terminal outcome=SUCCESS processed_count={new_processed_count}")

if __name__ == '__main__':
    main()
