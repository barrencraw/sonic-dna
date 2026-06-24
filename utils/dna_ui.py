#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    PROCESSING = "processing"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def log_structured(correlation_id, step, outcome, actor_id="system", extra=None):
    """Standardized JSON logging for telemetry."""
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": str(correlation_id),
        "chain_name": "dna_batch",
        "step": step,
        "outcome": outcome,
        "actor_id": actor_id
    }
    if extra:
        log_entry.update(extra)
    print(f"JSON_LOG: {json.dumps(log_entry)}")

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

def save_ledger_atomic(ledger_path, ledger, tmp_dir):
    tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
    with open(tmp_ledger, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_ledger, ledger_path)

def main(correlation_id=None, actor_id="system"):
    if correlation_id is None:
        correlation_id = uuid.uuid4()

    log_structured(correlation_id, "batch_start", "init", actor_id)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, "batch_end", DNAStatus.ERROR.value, actor_id, {"error": "Input file not found"})
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, "batch_end", DNAStatus.ERROR.value, actor_id, {"error": str(e)})
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, "batch_end", DNAStatus.ERROR.value, actor_id, {"error": str(e)})
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured(correlation_id, "batch_end", "no_items", actor_id)
        return

    ledger = load_ledger(ledger_path)

    # Load existing JSON output
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

    # Load existing CSV rows
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
            log_structured(correlation_id, "item_process", DNAStatus.SKIPPED.value, actor_id, {"dna": dna_str})
            continue

        log_structured(correlation_id, "item_process", DNAStatus.PROCESSING.value, actor_id, {"dna": dna_str})

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
            outcome = DNAStatus.SUCCESS.value

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    if new_processed_count > 0:
        log_structured(correlation_id, "atomic_write_start", "pending", actor_id)
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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

                # 4) Atomic renames
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

                log_structured(correlation_id, "atomic_write_complete", DNAStatus.SUCCESS.value, actor_id)

            except Exception as e:
                log_structured(correlation_id, "atomic_write_complete", DNAStatus.ERROR.value, actor_id, {"error": str(e)})
                raise PersistenceError("Failed to write output files atomically") from e

    log_structured(correlation_id, "batch_end", DNAStatus.SUCCESS.value, actor_id, {"new_items": new_processed_count})

if __name__ == '__main__':
    main()
