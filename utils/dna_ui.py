#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import getpass
from enum import Enum
from dataclasses import asdict
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    NO_NEW_DNA = "NO_NEW_DNA"

def log_observability(correlation_id, chain_name, step, outcome, latency_ms=None, actor_id=None, idempotency_key=None, error_message=None):
    log_data = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "actor_id": actor_id or getpass.getuser(),
    }
    if latency_ms is not None:
        log_data["latency_ms"] = latency_ms
    if idempotency_key:
        log_data["idempotency_key"] = idempotency_key
    if error_message:
        log_data["error_message"] = error_message

    print(f"[{log_data['timestamp']}] [{chain_name}] [{step}] outcome={log_data['outcome']} {f'key={idempotency_key}' if idempotency_key else ''}")

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
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def main():
    import uuid
    correlation_id = str(uuid.uuid4())
    chain_name = "dna_batch_chain"
    start_time = time.time()
    actor_id = getpass.getuser()

    log_observability(correlation_id, chain_name, "init", Outcome.START)

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(correlation_id, chain_name, "read_input", Outcome.ERROR, error_message=f"Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, chain_name, "load_rules", Outcome.ERROR, error_message=str(e))
        raise RuleLoadError(f"Could not load rules") from e

    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(correlation_id, chain_name, "read_input", Outcome.ERROR, error_message=str(e))
        raise DNAProcessingError(f"Failed to read input file") from e

    if not dna_list:
        log_observability(correlation_id, chain_name, "process_batch", Outcome.NO_NEW_DNA)
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
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability(correlation_id, chain_name, "check_idempotency", Outcome.SKIPPED, idempotency_key=idempotency_key)
            continue

        try:
            result = calculator.parse(dna_str)
            entry = asdict(result)
            parsed_json.append(entry)

            flat = flatten_parsed(result.rule, result.values)
            flat['dna'] = dna_str
            flat['rule'] = result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome_val = Outcome.SUCCESS
        except RuleParseError as e:
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome_val = Outcome.ERROR

        ledger[idempotency_key] = {
            'terminal_outcome': outcome_val.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_observability(correlation_id, chain_name, "parse_dna", outcome_val, idempotency_key=idempotency_key)
        new_processed_count += 1

    if new_processed_count > 0:
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
                log_observability(correlation_id, chain_name, "commit", Outcome.ERROR, error_message=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    latency_ms = int((time.time() - start_time) * 1000)
    log_observability(correlation_id, chain_name, "batch_complete", Outcome.END, latency_ms=latency_ms)
    print(f"[OK] Processed {new_processed_count} new DNA strings.")

if __name__ == '__main__':
    main()
