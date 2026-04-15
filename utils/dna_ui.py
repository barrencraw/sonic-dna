#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
import getpass
from datetime import datetime, timezone
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    NO_NEW_DNA = "NO_NEW_DNA"

def log_observability(step, outcome, latency_ms=0, idempotency_key=None, error_message=None):
    correlation_id = getattr(log_observability, "correlation_id", "N/A")
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": str(correlation_id),
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "latency_ms": latency_ms,
        "actor_id": getpass.getuser(),
        "idempotency_key": idempotency_key
    }
    if error_message:
        log_entry["error_message"] = error_message

    print(f"[OBSERVABILITY] {json.dumps(log_entry)}")

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

def main(data_dir=None):
    start_time = time.time()
    log_observability.correlation_id = uuid.uuid4()
    log_observability("start", Outcome.START)

    project_root = data_dir if data_dir else os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability("init", Outcome.ERROR, error_message=f"Input file not found: {input_file}")
        log_observability("complete", Outcome.END)
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability("load_rules", Outcome.ERROR, error_message=str(e))
        log_observability("complete", Outcome.END)
        raise RuleLoadError(f"Could not load rules") from e

    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("read_input", Outcome.ERROR, error_message=str(e))
        log_observability("complete", Outcome.END)
        raise DNAProcessingError(f"Failed to read input file") from e

    if not dna_list:
        log_observability("process", Outcome.NO_NEW_DNA)
        log_observability("complete", Outcome.END)
        return

    ledger = load_ledger(ledger_path)
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
        except Exception:
            parsed_json = []

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
        if dna_str in ledger or dna_str in seen_in_batch:
            log_observability("parse", Outcome.SKIPPED, idempotency_key=dna_str)
            continue

        seen_in_batch.add(dna_str)
        parse_start = time.time()
        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'rule': result.rule,
                'parsed': result.values
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result.rule, result.values)
            flat['dna'] = dna_str
            flat['rule'] = result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = Outcome.SUCCESS
            ledger[dna_str] = {
                'terminal_outcome': outcome.value,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except RuleParseError as e:
            outcome = Outcome.ERROR
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            ledger[dna_str] = {
                'terminal_outcome': outcome.value,
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        latency = int((time.time() - parse_start) * 1000)
        log_observability("parse", outcome, latency_ms=latency, idempotency_key=dna_str)
        new_processed_count += 1

    if new_processed_count > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        writer.writerow({k: row.get(k, '') for k in fieldnames})
                    cf.flush()
                    os.fsync(cf.fileno())

                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

                log_observability("persist", Outcome.SUCCESS)
            except Exception as e:
                log_observability("persist", Outcome.ERROR, error_message=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    total_latency = int((time.time() - start_time) * 1000)
    log_observability("complete", Outcome.END, latency_ms=total_latency)
    print(f"[OK] Processed {new_processed_count} new DNA strings.")

if __name__ == '__main__':
    main()
