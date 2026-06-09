#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
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

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if not os.path.isfile(input_path):
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
    # Migration: Check for legacy ledger filename
    legacy_ledger_path = os.path.join(os.path.dirname(ledger_path), 'processed_ledger.json')
    if not os.path.exists(ledger_path) and os.path.exists(legacy_ledger_path):
        try:
            shutil.move(legacy_ledger_path, ledger_path)
        except Exception:
            pass

    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and "ledger" in data:
                    return data
                else:
                    # Migration from legacy flat dict
                    return {"ledger": data, "system_heat": 0.0, "last_processed_timestamp": None}
        except Exception:
            pass
    return {"ledger": {}, "system_heat": 0.0, "last_processed_timestamp": None}

def save_ledger(ledger_path, state):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def log_structured(correlation_id, step, outcome, dna_sequence=None, error=None, latency_ms=None):
    log_data = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_processor",
        "step": step,
        "outcome": outcome,
        "actor_id": "system"
    }
    if dna_sequence:
        log_data["idempotency_key"] = dna_sequence
    if error:
        log_data["error"] = error
    if latency_ms is not None:
        log_data["latency_ms"] = latency_ms
    print(f"JSON_LOG: {json.dumps(log_data)}")

def main(correlation_id="unknown"):
    batch_start_time = time.perf_counter()
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, "initialize", "failure", error=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, "read_input", "failure", error=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured(correlation_id, "batch_start", "skipped", error="No DNA strings found")
        return

    state = load_ledger(ledger_path)
    ledger = state["ledger"]

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
                else:
                    # Migration: rename 'dna' to 'dna_sequence'
                    for item in parsed_json:
                        if 'dna' in item and 'dna_sequence' not in item:
                            item['dna_sequence'] = item.pop('dna')
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
                    # Migration: rename 'dna' to 'dna_sequence' in fieldnames
                    new_fieldnames = [fn if fn != 'dna' else 'dna_sequence' for fn in reader.fieldnames]
                    all_flattened_keys = set(new_fieldnames)
                    for row in reader:
                        new_row = { (k if k != 'dna' else 'dna_sequence'): v for k, v in row.items() }
                        csv_rows.append(new_row)
        except Exception:
            pass

    new_processed_count = 0
    for dna_sequence in dna_list:
        start_time = time.perf_counter()
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(correlation_id, "process_item", DNAStatus.SKIPPED.value, dna_sequence=dna_sequence)
            continue

        log_structured(correlation_id, "process_item", DNAStatus.PROCESSING.value, dna_sequence=dna_sequence)

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

        latency = (time.perf_counter() - start_time) * 1000
        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_structured(correlation_id, "process_item", outcome.value, dna_sequence=dna_sequence, latency_ms=latency)
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
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
                    json.dump(state, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic rename
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

                batch_latency = (time.perf_counter() - batch_start_time) * 1000
                log_structured(correlation_id, "commit", "success", latency_ms=batch_latency)

            except Exception as e:
                log_structured(correlation_id, "commit", "failure", error=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
