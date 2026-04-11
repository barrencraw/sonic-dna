#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
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
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if not os.path.isfile(input_path):
        return dna_list
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
                return data if isinstance(data, dict) else {}
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

    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

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
                data = json.load(jf)
                if isinstance(data, list):
                    parsed_json = data
        except Exception:
            pass

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
    seen_in_batch = set()

    for dna_str in dna_list:
        if dna_str in ledger:
            print(f"[Idempotency] key={dna_str} dedupe_hit=True terminal_outcome={ledger[dna_str]['terminal_outcome']}")
            continue

        if dna_str in seen_in_batch:
            continue
        seen_in_batch.add(dna_str)

        print(f"[Idempotency] key={dna_str} dedupe_hit=False terminal_outcome=processing")

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
            outcome = f"error: {str(e)}"
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        ledger[dna_str] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory
        # 2. Flush and sync
        # 3. Rename to final destination

        # We want to keep ledger_path in data/ and others in data/output/
        # To be truly atomic across all, they should ideally be on the same filesystem.
        # Usually data/ and data/output/ are.

        with tempfile.TemporaryDirectory(dir=data_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'toSequence_parsed.json')
            tmp_csv = os.path.join(tmp_dir, 'toSequence_parsed.csv')
            tmp_ledger = os.path.join(tmp_dir, 'processed_ledger.json')

            try:
                # JSON
                with open(tmp_json, 'w', encoding='utf-8') as f:
                    json.dump(parsed_json, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                # CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    f.flush()
                    os.fsync(f.fileno())

                # Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as f:
                    json.dump(ledger, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                # Commit
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                raise PersistenceError(f"Failed to write output files atomically: {e}")

        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     JSON -> {json_output_path}")
        print(f"     CSV  -> {csv_output_path}")
        print(f"     Ledger -> {ledger_path}")
    else:
        print("[OK] No new DNA strings to process.")

if __name__ == '__main__':
    main()
