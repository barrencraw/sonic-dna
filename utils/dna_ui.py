#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

def log_observability(correlation_id, chain_name, outcome, extra=None, actor_id='system'):
    payload = {
        'correlation_id': correlation_id,
        'chain_name': chain_name,
        'outcome': outcome,
        'actor_id': actor_id,
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    }
    if extra:
        payload.update(extra)
    print(f"| TELEMETRY | {json.dumps(payload)}")

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"

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
    correlation_id = str(uuid.uuid4())
    chain_name = "dna_batch_parsing"
    start_ts = time.time()

    log_observability(correlation_id, chain_name, Outcome.START.value, {'step': 'batch_init'})

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(correlation_id, chain_name, Outcome.ERROR.value, {
            'step': 'check_input',
            'error': f"Input file not found: {input_file}"
        })
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, chain_name, Outcome.ERROR.value, {
            'step': 'load_rules',
            'error': str(e)
        })
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(correlation_id, chain_name, Outcome.ERROR.value, {
            'step': 'read_input',
            'error': str(e)
        })
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(correlation_id, chain_name, Outcome.SKIPPED.value, {
            'step': 'validate_input',
            'message': "No DNA strings found"
        })
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
            log_observability(correlation_id, chain_name, Outcome.SKIPPED.value, {
                'step': 'idempotency_check',
                'idempotency_key': idempotency_key,
                'reason': 'already_processed'
            })
            continue

        item_start_ts = time.time()
        try:
            parsed_dna = calculator.parse(dna_str)
            entry = {
                'dna': parsed_dna.dna,
                'rule': parsed_dna.rule,
                'parsed': parsed_dna.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(parsed_dna.rule, parsed_dna.values)
            flat['dna'] = parsed_dna.dna
            flat['rule'] = parsed_dna.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS.value

        except RuleParseError as e:
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR.value

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        log_observability(correlation_id, chain_name, outcome, {
            'step': 'parse_item',
            'idempotency_key': idempotency_key,
            'latency_ms': int((time.time() - item_start_ts) * 1000)
        })
        new_processed_count += 1

    if new_processed_count > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                # Write JSON
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # Write CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # Write Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # Atomic renames
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

                log_observability(correlation_id, chain_name, Outcome.SUCCESS.value, {
                    'step': 'atomic_commit',
                    'new_processed_count': new_processed_count
                })

            except Exception as e:
                log_observability(correlation_id, chain_name, Outcome.ERROR.value, {
                    'step': 'atomic_commit',
                    'error': str(e)
                })
                raise PersistenceError("Failed to write output files atomically") from e

    latency_ms = int((time.time() - start_ts) * 1000)
    log_observability(correlation_id, chain_name, Outcome.END.value, {
        'step': 'batch_complete',
        'latency_ms': latency_ms,
        'total_processed': new_processed_count
    })

if __name__ == '__main__':
    main()
