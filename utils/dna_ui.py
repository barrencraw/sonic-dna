#!/usr/bin/env python3
import os
import json
import csv
import time
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

import tempfile
import shutil

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

    # Load system messages and integrity state
    system_msg_path = os.path.join(project_root, 'data', 'system_messages.json')
    system_messages = {}
    if os.path.exists(system_msg_path):
        with open(system_msg_path, 'r', encoding='utf-8') as f:
            system_messages = json.load(f)

    integrity_state_path = os.path.join(project_root, 'data', 'system_integrity.json')
    integrity_manager = IntegrityManager(integrity_state_path)

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

    from utils.dna_calculator import RuleParseError

    new_processed_count = 0
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            # Check for refusal if integrity is zero
            # To do this, we need to know the rule and values beforehand, or parse it first
            # Since parsing is deterministic and shouldn't have side effects, we'll parse first.
            try:
                result = calculator.parse(dna_str)
            except RuleParseError as e:
                # Handle parse error immediately
                parsed_json.append({'dna': dna_str, 'error': str(e)})
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = f"error: {str(e)}"

                # Apply standard wear even for errors?
                # "Others: -2 wear" according to plan.
                wear = integrity_manager.calculate_wear("error", {})
                new_integrity = integrity_manager.apply_wear(wear)
                print(f"[INTEGRITY] outcome=error wear={wear} new_integrity={new_integrity}")

                ledger[idempotency_key] = {
                    'terminal_outcome': outcome,
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
                }
                new_processed_count += 1
                continue

            # Identify if it's maintenance or if we're refused
            if not integrity_manager.can_process(result['rule'], result['values']):
                outcome = "REFUSAL"
                reason = system_messages.get('refusal_reason', "INTEGRITY_LEVEL_CRITICAL")
                hint = system_messages.get('next_action_hint', "Execute Maintenance.")
                print(f"[REFUSAL] key={idempotency_key} reason={reason} hint={hint}")
                # We do NOT record REFUSAL in the ledger to allow retries later
                continue

            # Process success
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

            # Apply wear
            wear = integrity_manager.calculate_wear(result['rule'], result['values'])
            new_integrity = integrity_manager.apply_wear(wear)
            consequence = system_messages.get('consequence_applied', "WEAR: {wear}, INTEGRITY: {integrity}")
            print(f"[INTEGRITY] outcome=success rule={result['rule']} wear={wear} new_integrity={new_integrity} msg={consequence.format(wear=wear, integrity=new_integrity)}")

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1

        except Exception as e:
            # Catch-all for unexpected processing errors
            print(f"[ERROR] processing {dna_str}: {e}")
            outcome = f"error: {str(e)}"
            # Record it as error
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            # Apply wear
            wear = integrity_manager.calculate_wear("error", {})
            new_integrity = integrity_manager.apply_wear(wear)

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
        tmp_integrity = os.path.join(tmp_dir, 'integrity.json')

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

            # 3) Write Ledger
            with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                json.dump(ledger, lf, indent=2)
                lf.flush()
                os.fsync(lf.fileno())

            # 4) Write Integrity State
            with open(tmp_integrity, 'w', encoding='utf-8') as itf:
                json.dump(integrity_manager.save_to_dict(), itf, indent=2)
                itf.flush()
                os.fsync(itf.fileno())

            # 5) Atomic rename (commit)
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)
            os.replace(tmp_integrity, integrity_state_path)

        except Exception as e:
            raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
