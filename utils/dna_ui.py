#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from enum import Enum
from dataclasses import dataclass
from utils.dna_calculator import DNACalculator, RuleParseError

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

class Outcome(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    START = "start"
    END = "end"
    NO_NEW_DNA = "no_new_dna"
    WARN = "warn"

def log_observability(correlation_id, step, outcome, latency_ms=None, actor_id=None, idempotency_key=None, error_message=None):
    log_data = {
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    if latency_ms is not None:
        log_data["latency_ms"] = int(latency_ms)
    if actor_id:
        log_data["actor_id"] = actor_id
    if idempotency_key:
        log_data["idempotency_key"] = idempotency_key
    if error_message:
        log_data["error_message"] = error_message

    print(f"[OBSERVABILITY] {json.dumps(log_data)}")

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

def dna_batch_chain(correlation_id="direct-run", actor_id="system"):
    start_time = time.time()
    log_observability(correlation_id, "START", Outcome.START, actor_id=actor_id)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(correlation_id, "FILE_CHECK", Outcome.ERROR, actor_id=actor_id, error_message=f"Input file not found: {input_file}")
        return Outcome.ERROR

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, "RULE_LOAD", Outcome.ERROR, actor_id=actor_id, error_message=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(correlation_id, "FILE_READ", Outcome.ERROR, actor_id=actor_id, error_message=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(correlation_id, "END", Outcome.NO_NEW_DNA, actor_id=actor_id)
        return Outcome.NO_NEW_DNA

    ledger = load_ledger(ledger_path)

    # Load existing JSON/CSV to maintain cumulative results
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list): parsed_json = []
        except Exception: pass

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
        except Exception: pass

    new_processed_count = 0
    for dna_str in dna_list:
        step_start = time.time()
        idempotency_key = dna_str

        if idempotency_key in ledger:
            log_observability(correlation_id, "STEP", Outcome.SKIPPED,
                              idempotency_key=idempotency_key, actor_id=actor_id)
            continue

        try:
            result = calculator.parse(dna_str)
            parsed_json.append({
                'dna': dna_str,
                'rule': result.rule,
                'parsed': result.values
            })

            flat = flatten_parsed(result.rule, result.values)
            flat['dna'] = dna_str
            flat['rule'] = result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS
            error_msg = None
        except RuleParseError as e:
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR
            error_msg = str(e)

        # Update ledger and log step
        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        latency = (time.time() - step_start) * 1000
        log_observability(correlation_id, "STEP", outcome, latency_ms=latency,
                          idempotency_key=idempotency_key, actor_id=actor_id, error_message=error_msg)
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC COMMIT
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)

                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        writer.writerow({k: row.get(k, '') for k in fieldnames})

                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
            except Exception as e:
                log_observability(correlation_id, "COMMIT", Outcome.ERROR, actor_id=actor_id, error_message=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    total_latency = (time.time() - start_time) * 1000
    log_observability(correlation_id, "END", Outcome.SUCCESS, latency_ms=total_latency, actor_id=actor_id)
    return Outcome.SUCCESS

def main():
    """Fallback main for existing calls."""
    dna_batch_chain()

if __name__ == '__main__':
    main()
