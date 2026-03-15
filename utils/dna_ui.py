#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
import datetime
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
    if not os.path.exists(input_path):
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
                return json.load(f)
        except Exception:
            return {}
    return {}

def process_dna_string(calculator, raw_dna):
    """
    Parses a single DNA string.
    Returns (processing_result, terminal_outcome).
    """
    try:
        result = calculator.parse(raw_dna)
        processing_result = {
            'dna': raw_dna,
            'rule': result['rule'],
            'parsed': result['values']
        }
        return processing_result, "SUCCESS"
    except RuleParseError as e:
        processing_result = {
            'dna': raw_dna,
            'error': str(e)
        }
        return processing_result, "ERROR"

def main(correlation_id=None, actor_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    if actor_id is None:
        actor_id = "unknown"

    chain_name = "dna_batch_chain"

    # [OBSERVABILITY] start
    print(json.dumps({
        "prefix": "[OBSERVABILITY]",
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": "start",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }))

    start_time = time.time()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        # [OBSERVABILITY] terminal error
        print(json.dumps({
            "prefix": "[OBSERVABILITY]",
            "correlation_id": correlation_id,
            "actor_id": actor_id,
            "chain_name": chain_name,
            "step": "load_rules",
            "outcome": "ERROR",
            "error": str(e),
            "latency_ms": int((time.time() - start_time) * 1000),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        # [OBSERVABILITY] terminal
        print(json.dumps({
            "prefix": "[OBSERVABILITY]",
            "correlation_id": correlation_id,
            "actor_id": actor_id,
            "chain_name": chain_name,
            "step": "read_input",
            "outcome": "NO_NEW_DATA",
            "latency_ms": int((time.time() - start_time) * 1000),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }))
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
    for raw_dna in dna_list:
        idempotency_key = raw_dna
        loop_start = time.time()

        if idempotency_key in ledger:
            # [OBSERVABILITY] dedupe
            print(json.dumps({
                "prefix": "[OBSERVABILITY]",
                "correlation_id": correlation_id,
                "actor_id": actor_id,
                "chain_name": chain_name,
                "step": "process_dna",
                "idempotency_key": idempotency_key,
                "outcome": "DEDUPE",
                "latency_ms": int((time.time() - loop_start) * 1000),
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }))
            continue

        processing_result, outcome = process_dna_string(calculator, raw_dna)

        parsed_json.append(processing_result)

        if outcome == "SUCCESS":
            flat = flatten_parsed(processing_result['rule'], processing_result['parsed'])
            flat['dna'] = raw_dna
            flat['rule'] = processing_result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
        else:
            flat = {'dna': raw_dna, 'error': processing_result['error']}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        new_processed_count += 1

        # [OBSERVABILITY] per string result
        print(json.dumps({
            "prefix": "[OBSERVABILITY]",
            "correlation_id": correlation_id,
            "actor_id": actor_id,
            "chain_name": chain_name,
            "step": "process_dna",
            "idempotency_key": idempotency_key,
            "outcome": outcome,
            "latency_ms": int((time.time() - loop_start) * 1000),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }))

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                # 1) JSON
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic rename
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                # [OBSERVABILITY] persistence error
                print(json.dumps({
                    "prefix": "[OBSERVABILITY]",
                    "correlation_id": correlation_id,
                    "actor_id": actor_id,
                    "chain_name": chain_name,
                    "step": "persistence",
                    "outcome": "ERROR",
                    "error": str(e),
                    "latency_ms": int((time.time() - start_time) * 1000),
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                }))
                raise PersistenceError("Failed to write output files atomically") from e

    # [OBSERVABILITY] final success
    print(json.dumps({
        "prefix": "[OBSERVABILITY]",
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": "complete",
        "outcome": "SUCCESS",
        "new_processed_count": new_processed_count,
        "latency_ms": int((time.time() - start_time) * 1000),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }))

if __name__ == '__main__':
    main()
