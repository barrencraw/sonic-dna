#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError, ParsedDNA

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

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    NO_NEW_DNA = "NO_NEW_DNA"

def log_observability(step, outcome, correlation_id=None, dna=None, error=None, extra=None):
    payload = {
        "correlation_id": correlation_id or "N/A",
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "actor_id": "system"
    }
    if dna:
        payload["dna"] = dna
    if error:
        payload["error"] = str(error)
    if extra:
        payload.update(extra)

    print(f"| TELEMETRY | {json.dumps(payload)}")

def main(data_dir=None):
    correlation_id = str(uuid.uuid4())
    log_observability("batch_start", Outcome.START, correlation_id=correlation_id)
    # Determine file paths
    project_root = data_dir or os.getcwd()
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
    batch_results = []

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability("dna_process", Outcome.SKIPPED, correlation_id=correlation_id, dna=dna_str, extra={"reason": "idempotency_hit"})
            continue

        log_observability("dna_process", Outcome.PROCESSING, correlation_id=correlation_id, dna=dna_str)

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

            outcome_val = Outcome.SUCCESS
            error_msg = None

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome_val = Outcome.ERROR
            error_msg = str(e)

        # Update ledger in-memory
        ledger[idempotency_key] = {
            'terminal_outcome': outcome_val.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        batch_results.append(outcome_val)
        new_processed_count += 1
        log_observability("dna_process", outcome_val, correlation_id=correlation_id, dna=dna_str, error=error_msg)

    # ATOMIC WRITE PATTERN:
    if new_processed_count > 0:
        # We need to write JSON, CSV, and Ledger atomically.
        # Use output_folder for temp files to stay on same mount point.
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

                # 4) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                log_observability("batch_commit", Outcome.ERROR, correlation_id=correlation_id, error=e)
                raise PersistenceError("Failed to write output files atomically") from e

    # Determine final batch outcome
    if not dna_list:
        final_outcome = Outcome.NO_NEW_DNA
    elif new_processed_count == 0:
        final_outcome = Outcome.NO_NEW_DNA
    else:
        has_success = Outcome.SUCCESS in batch_results
        has_error = Outcome.ERROR in batch_results
        if has_success and has_error:
            final_outcome = Outcome.PARTIAL_SUCCESS
        elif has_error:
            final_outcome = Outcome.ERROR
        else:
            final_outcome = Outcome.SUCCESS

    log_observability("batch_end", final_outcome, correlation_id=correlation_id, extra={"new_processed": new_processed_count})

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    if new_processed_count > 0:
        print(f"     JSON   → {json_output_path}")
        print(f"     CSV    → {csv_output_path}")
        print(f"     Ledger → {ledger_path}")

if __name__ == '__main__':
    main()
