#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(enum.Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def log_structured(correlation_id, step, outcome, idempotency_key=None, latency_ms=None, error_detail=None):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_parsing",
        "step": step,
        "outcome": outcome,
    }
    if idempotency_key:
        log_entry["idempotency_key"] = idempotency_key
    if latency_ms is not None:
        log_entry["latency_ms"] = round(latency_ms, 2)
    if error_detail:
        log_entry["error_detail"] = error_detail

    print(f"JSON_LOG: {json.dumps(log_entry)}")

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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('ledger', {}) if isinstance(data, dict) and 'ledger' in data else data
        except Exception:
            return {}
    return {}

def main(correlation_id="batch-default", actor_id="system"):
    start_time = time.time()
    log_structured(correlation_id, "start", "in_progress")

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, "end", "skipped", error_detail="Input file not found")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, "end", "error", error_detail=str(e))
        raise RuleLoadError(f"Could not load rules") from e

    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, "end", "error", error_detail=str(e))
        raise DNAProcessingError(f"Failed to read input file") from e

    if not dna_list:
        log_structured(correlation_id, "end", "skipped", error_detail="No DNA strings found")
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
        item_start = time.time()
        idempotency_key = dna_str

        if idempotency_key in ledger:
            log_structured(correlation_id, "parsing_item", DNAStatus.SKIPPED.value,
                           idempotency_key=idempotency_key, latency_ms=(time.time()-item_start)*1000)
            continue

        try:
            result = calculator.parse(dna_str)
            entry = {'dna': dna_str, 'rule': result['rule'], 'parsed': result['values']}
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.SUCCESS.value
            error_msg = None
        except RuleParseError as e:
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value
            error_msg = str(e)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }
        log_structured(correlation_id, "parsing_item", outcome,
                       idempotency_key=idempotency_key,
                       latency_ms=(time.time()-item_start)*1000,
                       error_detail=error_msg)
        new_processed_count += 1

    if new_processed_count > 0:
        log_structured(correlation_id, "commit_phase", "in_progress")
        commit_start = time.time()
        try:
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

                with open(tmp_json, 'w', encoding='utf-8') as f:
                    json.dump(parsed_json, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        writer.writerow({k: row.get(k, '') for k in fieldnames})
                    f.flush()
                    os.fsync(f.fileno())

                with open(tmp_ledger, 'w', encoding='utf-8') as f:
                    json.dump({'ledger': ledger}, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            log_structured(correlation_id, "commit_phase", "success",
                           latency_ms=(time.time()-commit_start)*1000)
        except Exception as e:
            log_structured(correlation_id, "commit_phase", "error", error_detail=str(e))
            raise PersistenceError("Atomic commit failed") from e

    log_structured(correlation_id, "end", "success", latency_ms=(time.time()-start_time)*1000)

if __name__ == '__main__':
    main()
