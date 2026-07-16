#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    REFUSED = "REFUSED"

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
    """Raised when the system is in thermal lockout."""
    pass

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

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key=None, outcome_detail=None):
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {'ledger': {}, 'system_heat': 0.0, 'last_heat_timestamp': None}
                if 'ledger' not in data:
                    # Backward compatibility for flat ledger
                    return {'ledger': data, 'system_heat': 0.0, 'last_heat_timestamp': None}
                return data
        except Exception:
            return {'ledger': {}, 'system_heat': 0.0, 'last_heat_timestamp': None}
    return {'ledger': {}, 'system_heat': 0.0, 'last_heat_timestamp': None}

def save_ledger_atomic(ledger_path, state):
    dir_name = os.path.dirname(ledger_path)
    with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
        json.dump(state, tf, indent=2)
        temp_name = tf.name
    os.replace(temp_name, ledger_path)

MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0  # units per second

def run_batch(correlation_id=None, actor_id="system"):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    start_time = time.perf_counter()
    chain_name = "DNA Batch Parsing"

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, actor_id, chain_name, "init", "ERROR", 0, outcome_detail=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, actor_id, chain_name, "init", "ERROR", 0, outcome_detail=f"Rule load error: {str(e)}")
        raise RuleLoadError(f"Could not load rules") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, actor_id, chain_name, "read", "ERROR", 0, outcome_detail=f"Read error: {str(e)}")
        raise DNAProcessingError(f"Failed to read input file") from e

    state = load_ledger(ledger_path)
    ledger = state['ledger']
    current_heat = state.get('system_heat', 0.0)
    last_time_str = state.get('last_heat_timestamp')

    # Dissipate heat
    now = datetime.datetime.now(datetime.timezone.utc)
    if last_time_str:
        last_time = datetime.datetime.fromisoformat(last_time_str.replace('Z', '+00:00'))
        elapsed = (now - last_time).total_seconds()
        reduction = elapsed * COOLING_RATE
        current_heat = max(0.0, current_heat - reduction)

    state['system_heat'] = current_heat
    state['last_heat_timestamp'] = now.isoformat().replace('+00:00', 'Z')

    if not dna_list:
        save_ledger_atomic(ledger_path, state)
        log_structured(correlation_id, actor_id, chain_name, "process", "SUCCESS", int((time.perf_counter() - start_time)*1000), outcome_detail="No sequences to process. Heat dissipated.")
        return

    # Load existing outputs for appending
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list): parsed_json = []
        except Exception: pass

    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as cf:
                reader = csv.DictReader(cf)
                if reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    csv_rows = list(reader)
        except Exception: pass

    new_processed_count = 0
    error_to_raise = None

    try:
        for dna_str in dna_list:
            item_start = time.perf_counter()
            if dna_str in ledger:
                log_structured(correlation_id, actor_id, chain_name, "item_parse", DNAStatus.SKIPPED.value,
                               int((time.perf_counter() - item_start)*1000), idempotency_key=dna_str,
                               outcome_detail=f"Already processed with outcome: {ledger[dna_str]['terminal_outcome']}")
                continue

            # Check thermal lockout
            if current_heat + HEAT_PER_SEQ > MAX_HEAT:
                log_structured(correlation_id, actor_id, chain_name, "item_parse", DNAStatus.REFUSED.value,
                               int((time.perf_counter() - item_start)*1000), idempotency_key=dna_str,
                               outcome_detail="Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines.")
                error_to_raise = ThermalOverloadError("Thermal Lockout")
                break

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
                outcome_detail = "Successfully parsed"
            except RuleParseError as e:
                parsed_json.append({'dna': dna_str, 'error': str(e)})
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR.value
                outcome_detail = str(e)

            # Update heat and ledger
            current_heat += HEAT_PER_SEQ
            ledger[dna_str] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
            }
            new_processed_count += 1
            log_structured(correlation_id, actor_id, chain_name, "item_parse", outcome,
                           int((time.perf_counter() - item_start)*1000), idempotency_key=dna_str,
                           outcome_detail=outcome_detail)

    finally:
        # Atomic commit of whatever we processed
        state['system_heat'] = current_heat
        state['last_heat_timestamp'] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')

        if new_processed_count > 0 or error_to_raise:
            try:
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
                            writer.writerow({k: row.get(k, '') for k in fieldnames})
                        cf.flush()
                        os.fsync(cf.fileno())

                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

                save_ledger_atomic(ledger_path, state)
            except Exception as e:
                log_structured(correlation_id, actor_id, chain_name, "commit", "ERROR", 0, outcome_detail=f"Persistence error: {str(e)}")
                if not error_to_raise:
                    error_to_raise = PersistenceError("Failed to write output files atomically")
        else:
            # Even if nothing processed, save heat dissipation
            save_ledger_atomic(ledger_path, state)

    if error_to_raise:
        raise error_to_raise

    log_structured(correlation_id, actor_id, chain_name, "process", "SUCCESS",
                   int((time.perf_counter() - start_time)*1000), outcome_detail=f"Processed {new_processed_count} new sequences.")

def main():
    # CLI entry point if called directly
    try:
        run_batch()
    except DNAProcessingError as e:
        print(f"Error: {e}")
        import sys
        sys.exit(1)

if __name__ == '__main__':
    main()
