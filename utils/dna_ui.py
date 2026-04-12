#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import getpass
import tempfile
import shutil
from datetime import datetime, timezone
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    NO_NEW_DNA = "NO_NEW_DNA"

def log_observability(chain_name, step, outcome, correlation_id=None, latency_ms=0, idempotency_key=None, error_message=None):
    """
    Structured logging for observability.
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "latency_ms": latency_ms,
        "actor_id": getpass.getuser(),
        "idempotency_key": idempotency_key
    }
    if error_message:
        log_entry["error_message"] = error_message

    print(f"[{log_entry['timestamp']}] [{log_entry['chain_name']}] step={step} outcome={log_entry['outcome']} key={idempotency_key}")
    return log_entry["correlation_id"]

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
    correlation_id = log_observability("dna_batch_chain", "init", Outcome.START)
    start_time = time.time()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability("dna_batch_chain", "input_check", Outcome.ERROR,
                          correlation_id=correlation_id, error_message=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability("dna_batch_chain", "rule_load", Outcome.ERROR,
                          correlation_id=correlation_id, error_message=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("dna_batch_chain", "read_input", Outcome.ERROR,
                          correlation_id=correlation_id, error_message=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability("dna_batch_chain", "process_loop", Outcome.NO_NEW_DNA, correlation_id=correlation_id)
        return

    ledger = load_ledger(ledger_path)
    seen_in_batch = set()

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

    new_processed_count = 0
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in seen_in_batch or idempotency_key in ledger:
            log_observability("dna_batch_chain", "idempotency_check", Outcome.SKIPPED,
                              correlation_id=correlation_id, idempotency_key=idempotency_key)
            continue

        seen_in_batch.add(idempotency_key)

        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'rule': result.rule,
                'parsed': result.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result.rule, result.values)
            flat['dna'] = dna_str
            flat['rule'] = result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS

        except RuleParseError as e:
            error_msg = str(e)
            parsed_json.append({
                'dna': dna_str,
                'error': error_msg
            })
            flat = {'dna': dna_str, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR
            log_observability("dna_batch_chain", "parse_dna", outcome,
                              correlation_id=correlation_id, idempotency_key=idempotency_key, error_message=error_msg)

        if outcome == Outcome.SUCCESS:
            log_observability("dna_batch_chain", "parse_dna", outcome,
                              correlation_id=correlation_id, idempotency_key=idempotency_key)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)
        try:
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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

                # 3) Write Ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            log_observability("dna_batch_chain", "atomic_commit", Outcome.SUCCESS, correlation_id=correlation_id)
        except Exception as e:
            log_observability("dna_batch_chain", "atomic_commit", Outcome.ERROR,
                              correlation_id=correlation_id, error_message=str(e))
            raise PersistenceError("Failed to write output files atomically") from e

    latency = int((time.time() - start_time) * 1000)
    log_observability("dna_batch_chain", "batch_complete", Outcome.END,
                      correlation_id=correlation_id, latency_ms=latency)

if __name__ == '__main__':
    main()
