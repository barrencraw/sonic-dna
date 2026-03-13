#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError
from utils.integrity_manager import IntegrityManager

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads DNA strings from the input file, one per line.
    Returns a list of stripped, non-empty DNA strings.
    """
    dna_list = []
    if not os.path.exists(input_path):
        return dna_list
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

class DNAProcessingError(Exception):
    pass

class RuleLoadError(DNAProcessingError):
    pass

class PersistenceError(DNAProcessingError):
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
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    integrity_path = os.path.join(project_root, 'data', 'system_integrity.json')
    messages_path = os.path.join(project_root, 'data', 'system_messages.json')

    ensure_folder(output_folder)
    input_file = os.path.join(raw_folder, 'toSequence.txt')

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules: {e}")

    integrity_mgr = IntegrityManager(integrity_path, messages_path)
    dna_list = read_input_file(input_file)
    if not dna_list:
        return

    ledger = load_ledger(ledger_path)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
        except Exception:
            pass

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
        if dna_str in ledger:
            continue

        try:
            # 1. Parse DNA
            res = calculator.parse(dna_str)

            # 2. Check Integrity / Refusal
            change = integrity_mgr.calculate_change(res)
            current_integrity = integrity_mgr.get_integrity()

            # Refusal logic: if integrity 0 and it's not a restoration string (change <= 0)
            if current_integrity <= 0 and change <= 0:
                outcome = "REFUSAL"
                entry = {
                    "dna": dna_str,
                    "outcome": outcome,
                    "refusal_reason": integrity_mgr.get_message("refusal_reason"),
                    "next_action_hint": integrity_mgr.get_message("next_action_hint")
                }
            else:
                outcome = "SUCCESS"
                integrity_mgr.apply_change(change)
                entry = {
                    "dna": dna_str,
                    "rule": res['rule'],
                    "parsed": res['values'],
                    "outcome": outcome,
                    "integrity_after": integrity_mgr.get_integrity()
                }
                if change < 0:
                    entry["note"] = integrity_mgr.get_message("consequence_applied")

            parsed_json.append(entry)

            # CSV flat row
            flat = {"dna": dna_str, "outcome": outcome}
            if outcome == "SUCCESS":
                flat.update(flatten_parsed(res['rule'], res['values']))
                flat["integrity_after"] = entry["integrity_after"]
            else:
                flat["refusal_reason"] = entry.get("refusal_reason", "")

            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        except RuleParseError as e:
            outcome = "ERROR"
            entry = {"dna": dna_str, "outcome": outcome, "error": str(e)}
            parsed_json.append(entry)
            flat = {"dna": dna_str, "outcome": outcome, "error": str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        # Update ledger for each DNA
        ledger[dna_str] = {
            "terminal_outcome": outcome,
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }
        new_processed_count += 1

    # ATOMIC COMMIT
    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'out.json')
        tmp_csv = os.path.join(tmp_dir, 'out.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
        tmp_integrity = os.path.join(tmp_dir, 'integrity.json')

        try:
            with open(tmp_json, 'w') as f:
                json.dump(parsed_json, f, indent=2)

            fieldnames = sorted(all_flattened_keys)
            with open(tmp_csv, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for r in csv_rows:
                    writer.writerow({k: r.get(k, "") for k in fieldnames})

            with open(tmp_ledger, 'w') as f:
                json.dump(ledger, f, indent=2)

            integrity_mgr.save_state(tmp_integrity)

            # Sync and swap
            for tmp, dest in [(tmp_json, json_output_path), (tmp_csv, csv_output_path),
                               (tmp_ledger, ledger_path), (tmp_integrity, integrity_path)]:
                os.replace(tmp, dest)
        except Exception as e:
            raise PersistenceError(f"Atomic write failed: {e}")

    print(f"[OK] Processed {new_processed_count} new entries.")

if __name__ == "__main__":
    main()
