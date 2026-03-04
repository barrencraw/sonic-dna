#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from utils.dna_calculator import DNACalculator, RuleParseError
from utils.observability import StructuredLogger

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
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def main(correlation_id=None):
    start_time = time.time()
    logger = StructuredLogger(correlation_id=correlation_id)
    logger.log("batch_start", "processing")

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        logger.log("batch_end", "error", {"error": "input_file_missing"})
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        logger.log("batch_end", "error", {"error": str(e)})
        raise RuleLoadError(f"Could not load rules") from e

    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        logger.log("batch_end", "error", {"error": str(e)})
        raise DNAProcessingError(f"Failed to read input file") from e

    if not dna_list:
        logger.log("batch_end", "success", {"msg": "no_dna_found"})
        return

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

    new_processed_count = 0
    for dna_str in dna_list:
        if dna_str in ledger:
            logger.log("item_process", "dedupe", {"idempotency_key": dna_str})
            continue

        try:
            result = calculator.parse(dna_str)
            entry = {'dna': dna_str, 'rule': result['rule'], 'parsed': result['values']}
            parsed_json.append(entry)
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"
        except RuleParseError as e:
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "error"

        ledger[dna_str] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        logger.log("item_process", outcome, {"idempotency_key": dna_str})
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE + COMMIT
        try:
            # We use the same folder as the output to ensure we're on the same filesystem for os.replace
            with tempfile.TemporaryDirectory(dir=os.path.dirname(ledger_path)) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'toSequence_parsed.json')
                tmp_csv = os.path.join(tmp_dir, 'toSequence_parsed.csv')
                tmp_ledger = os.path.join(tmp_dir, 'processed_ledger.json')

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

                # Commit
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

        except Exception as e:
            logger.log("batch_end", "error", {"error": f"persistence_failure: {e}"})
            raise PersistenceError(f"Failed to commit outputs: {e}")

    latency = int((time.time() - start_time) * 1000)
    logger.log("batch_end", "success", {"new_items": new_processed_count, "latency_ms": latency})

if __name__ == '__main__':
    main()
