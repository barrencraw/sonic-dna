#!/usr/bin/env python3
import os
import json
import csv
import time
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

import tempfile
import shutil

import datetime

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
    """Raised when the processing unit is in thermal lockout."""
    def __init__(self, message="Thermal Lockout"):
        super().__init__(message)
        self.consequence = "Heat Accumulation"
        self.reason = "Thermal Lockout"
        self.hint = "Wait for dissipation. The system is indifferent to your deadlines."

def log_structured(correlation_id, step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None, actor_id="operator", chain_name="dna_batch_parser"):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0

def calculate_cooling(ledger, current_time):
    system_heat = ledger.get("system_heat", 0.0)
    last_updated_str = ledger.get("last_updated")
    if last_updated_str:
        try:
            last_time_str = last_updated_str
            if last_time_str.endswith('Z'):
                last_time_str = last_time_str[:-1] + '+00:00'
            last_updated = datetime.datetime.fromisoformat(last_time_str)
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=datetime.timezone.utc)
            elapsed = (current_time - last_updated).total_seconds()
            if elapsed > 0:
                cooling = elapsed * COOLING_RATE
                system_heat = max(0.0, system_heat - cooling)
        except Exception:
            pass
    else:
        system_heat = 0.0
    return system_heat

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    ledger_dir = os.path.dirname(ledger_path)
    if not ledger_dir:
        ledger_dir = '.'
    with tempfile.NamedTemporaryFile('w', dir=ledger_dir, delete=False, encoding='utf-8') as tf:
        json.dump(ledger, tf, indent=2)
        tf.flush()
        os.fsync(tf.fileno())
        temp_name = tf.name
    try:
        os.replace(temp_name, ledger_path)
    except Exception as e:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise e

def run_batch(correlation_id=None):
    # Determine file paths
    project_root = os.getcwd()
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

    # Calculate cooling
    current_time = datetime.datetime.now(datetime.timezone.utc)
    system_heat = calculate_cooling(ledger, current_time)

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
    error_occurred = False
    error_to_raise = None

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str

            # Check flat or nested ledger compatibility
            existing_outcome = None
            if idempotency_key in ledger:
                existing_outcome = ledger[idempotency_key].get('terminal_outcome')

            if existing_outcome in ['success', 'error']:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={existing_outcome}")
                log_structured(correlation_id, "idempotency_check", "skipped", idempotency_key=idempotency_key, outcome_detail="dedupe_hit")
                continue

            # Thermal check before processing
            if system_heat + HEAT_PER_SEQ > MAX_HEAT:
                log_structured(correlation_id, "thermal_check", "refused", idempotency_key=idempotency_key, outcome_detail="Thermal Lockout")
                error_to_raise = ThermalOverloadError()
                break

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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
                outcome = "success"

            except RuleParseError as e:
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e)
                })
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "error"

            # Apply heat consequence and update state
            system_heat += HEAT_PER_SEQ
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            }
            log_structured(correlation_id, "process_dna", outcome, idempotency_key=idempotency_key)
            new_processed_count += 1
    except Exception as e:
        error_occurred = True
        error_to_raise = e

    finally:
        try:
            # Persist state
            ledger["system_heat"] = system_heat
            ledger["last_updated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Always save the ledger to keep track of heat/cooling
            save_ledger(ledger_path, ledger)

            # Only rewrite output files if new items were actually processed
            if new_processed_count > 0:
                with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                    tmp_json = os.path.join(tmp_dir, 'output.json')
                    tmp_csv = os.path.join(tmp_dir, 'output.csv')

                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())

                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

        except Exception as e:
            if not error_occurred and error_to_raise is None:
                if not isinstance(e, DNAProcessingError):
                    raise PersistenceError("Failed to write output files atomically") from e
                raise e

    if error_to_raise is not None:
        raise error_to_raise

    total_ledger_items = sum(1 for k in ledger if k not in ["system_heat", "last_updated"])
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {total_ledger_items}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

main = run_batch

if __name__ == '__main__':
    main()
