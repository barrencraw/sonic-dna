#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError, ParsedDNA

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"

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

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def log_observability(step, outcome, correlation_id, **kwargs):
    """
    Standardized structured logging.
    """
    entry = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'correlation_id': correlation_id,
        'chain_name': 'dna_batch_chain',
        'step': step,
        'outcome': outcome.value if isinstance(outcome, Outcome) else str(outcome)
    }
    entry.update(kwargs)
    print(f"| TELEMETRY | {json.dumps(entry)}")

def main():
    correlation_id = str(uuid.uuid4())
    log_observability("batch_start", Outcome.START, correlation_id)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability("input_check", Outcome.ERROR, correlation_id, error=f"Input file not found: {input_file}")
        log_observability("batch_end", Outcome.END, correlation_id)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability("rule_load", Outcome.ERROR, correlation_id, error=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("input_read", Outcome.ERROR, correlation_id, error=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability("input_read", Outcome.SKIPPED, correlation_id, reason="No DNA strings found")
        log_observability("batch_end", Outcome.END, correlation_id)
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

    new_processed_count = 0
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability("idempotency_check", Outcome.SKIPPED, correlation_id, key=idempotency_key, dedupe_hit=True, terminal_outcome=ledger[idempotency_key].get('terminal_outcome'))
            continue

        log_observability("processing_item", Outcome.PROCESSING, correlation_id, key=idempotency_key)

        try:
            result = calculator.parse(dna_str)
            # result is a ParsedDNA object
            entry = {
                'dna': result.dna,
                'rule': result.rule,
                'parsed': result.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result.rule, result.values)
            flat['dna'] = result.dna
            flat['rule'] = result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome_val = Outcome.SUCCESS
            error_msg = None

        except RuleParseError as e:
            error_msg = str(e)
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': error_msg
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome_val = Outcome.ERROR

        # Update ledger for this item
        ledger[idempotency_key] = {
            'terminal_outcome': outcome_val.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_observability("item_complete", outcome_val, correlation_id, key=idempotency_key, error=error_msg)
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
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

                log_observability("persistence", Outcome.SUCCESS, correlation_id, count=new_processed_count)

            except Exception as e:
                log_observability("persistence", Outcome.ERROR, correlation_id, error=str(e))
                raise PersistenceError("Failed to write output files atomically") from e
    else:
        log_observability("batch_complete", Outcome.SUCCESS, correlation_id, message="No new DNA processed")

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    log_observability("batch_end", Outcome.END, correlation_id)

if __name__ == '__main__':
    main()
