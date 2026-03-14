#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
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

def log_event(correlation_id, actor_id, step, outcome, latency_ms=None, idempotency_key=None):
    """Emits a structured [OBSERVABILITY] log."""
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "chain_name": "dna_batch_chain",
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "step": step,
        "outcome": outcome,
    }
    if latency_ms is not None:
        log_data["latency_ms"] = round(latency_ms, 2)
    if idempotency_key is not None:
        log_data["idempotency_key"] = idempotency_key

    print(f"[OBSERVABILITY] {json.dumps(log_data)}")

def process_dna_string(dna_str, calculator, ledger, parsed_json, csv_rows, all_flattened_keys):
    """
    Processes a single DNA string. Returns (outcome, is_new).
    """
    if dna_str in ledger:
        return ledger[dna_str].get('terminal_outcome', 'SUCCESS'), False

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
        return "SUCCESS", True

    except RuleParseError as e:
        # On parse error, record as error entry
        parsed_json.append({
            'dna': dna_str,
            'error': str(e)
        })
        # Also put a row in CSV listing error
        flat = {'dna': dna_str, 'error': str(e)}
        csv_rows.append(flat)
        all_flattened_keys.update(flat.keys())
        return "ERROR", True

def main(correlation_id="N/A", actor_id="system"):
    start_time = time.time()
    log_event(correlation_id, actor_id, "start", "STARTED")

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
        log_event(correlation_id, actor_id, "load_rules", "ERROR")
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_event(correlation_id, actor_id, "read_input", "ERROR")
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_event(correlation_id, actor_id, "complete", "NO_NEW_DATA", latency_ms=(time.time()-start_time)*1000)
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
        step_start = time.time()
        outcome, is_new = process_dna_string(dna_str, calculator, ledger, parsed_json, csv_rows, all_flattened_keys)

        if is_new:
            ledger[dna_str] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            new_processed_count += 1
            log_event(correlation_id, actor_id, "process_dna", outcome,
                      latency_ms=(time.time()-step_start)*1000, idempotency_key=dna_str)
        else:
            log_event(correlation_id, actor_id, "process_dna", "DEDUPE",
                      latency_ms=(time.time()-step_start)*1000, idempotency_key=dna_str)

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
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # Atomic renames
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                log_event(correlation_id, actor_id, "persistence", "ERROR")
                raise PersistenceError("Failed to write output files atomically") from e

    log_event(correlation_id, actor_id, "complete", "SUCCESS", latency_ms=(time.time()-start_time)*1000)

if __name__ == '__main__':
    main()
