#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(Enum):
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

class ThermalOverloadError(DNAProcessingError):
    """Raised when system heat exceeds threshold."""
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

def log_structured(timestamp, correlation_id, chain_name, step, outcome, actor_id, idempotency_key=None, latency_ms=None, error_detail=None, hint=None):
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "actor_id": actor_id
    }
    if idempotency_key:
        log_data["idempotency_key"] = idempotency_key
    if latency_ms is not None:
        log_data["latency_ms"] = round(latency_ms, 2)
    if error_detail:
        log_data["error_detail"] = error_detail
    if hint:
        log_data["hint"] = hint

    print(f"JSON_LOG: {json.dumps(log_data)}")

def load_ledger(ledger_path):
    default_state = {
        "system_heat": 0.0,
        "last_processed_timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Handle legacy flat format if necessary
                if "ledger" not in data:
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        "ledger": data
                    }
                return data
        except Exception:
            return default_state
    return default_state

def main(correlation_id=None, actor_id="system"):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Start log
    now_iso = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    log_structured(now_iso, correlation_id, "dna_batch", "start", "processing", actor_id)

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(now_iso, correlation_id, "dna_batch", "rule_load", "error", actor_id, error_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(now_iso, correlation_id, "dna_batch", "input_read", "error", actor_id, error_detail=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured(now_iso, correlation_id, "dna_batch", "complete", "skipped", actor_id, hint="No DNA strings found")
        return

    full_ledger_data = load_ledger(ledger_path)
    ledger = full_ledger_data["ledger"]
    system_heat = full_ledger_data.get("system_heat", 0.0)
    last_ts_str = full_ledger_data.get("last_processed_timestamp")

    # Calculate dissipation
    last_ts = time.time()
    if last_ts_str:
        try:
            last_ts = time.mktime(time.strptime(last_ts_str, '%Y-%m-%dT%H:%M:%SZ'))
        except ValueError:
            pass

    elapsed = time.time() - last_ts
    system_heat = max(0.0, system_heat - (elapsed * 0.5))

    # Load existing JSON/CSV output
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
        item_start_time = time.perf_counter()
        idempotency_key = dna_str

        # Check idempotency - only skip SUCCESS
        if idempotency_key in ledger and ledger[idempotency_key].get('terminal_outcome') == DNAStatus.SUCCESS.value:
            log_structured(
                time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                correlation_id, "dna_batch", "item_process", DNAStatus.SKIPPED.value, actor_id,
                idempotency_key=idempotency_key
            )
            continue

        # Thermal check
        if system_heat > 100.0:
            outcome = DNAStatus.REFUSED.value
            latency_ms = (time.perf_counter() - item_start_time) * 1000
            log_structured(
                time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                correlation_id, "dna_batch", "item_process", outcome, actor_id,
                idempotency_key=idempotency_key, latency_ms=latency_ms,
                hint="Dissipation required. System indifferent to urgency."
            )
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }
            new_processed_count += 1
            continue

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
            outcome = DNAStatus.SUCCESS.value
            system_heat += 5.0

        except RuleParseError as e:
            outcome = DNAStatus.ERROR.value
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        latency_ms = (time.perf_counter() - item_start_time) * 1000
        log_structured(
            time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            correlation_id, "dna_batch", "item_process", outcome, actor_id,
            idempotency_key=idempotency_key, latency_ms=latency_ms
        )

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }
        new_processed_count += 1

    if new_processed_count > 0:
        full_ledger_data["system_heat"] = system_heat
        full_ledger_data["last_processed_timestamp"] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

        # ATOMIC WRITE PATTERN
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            # Use same dir as ledger for atomic rename
            ledger_dir = os.path.dirname(ledger_path)
            with tempfile.TemporaryDirectory(dir=ledger_dir) as tmp_ledger_dir:
                tmp_ledger = os.path.join(tmp_ledger_dir, 'ledger.json')

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
                        json.dump(full_ledger_data, lf, indent=2)
                        lf.flush()
                        os.fsync(lf.fileno())

                    # 4) Atomic replace
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)
                    os.replace(tmp_ledger, ledger_path)

                except Exception as e:
                    log_structured(
                        time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        correlation_id, "dna_batch", "persistence", "error", actor_id, error_detail=str(e)
                    )
                    raise PersistenceError("Failed to write output files atomically") from e

    log_structured(
        time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        correlation_id, "dna_batch", "complete", "success", actor_id
    )

if __name__ == '__main__':
    main()
