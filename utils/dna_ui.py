#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
from enum import Enum
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
    """Raised when system heat exceeds safety threshold."""
    pass

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# Thermal constants
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0  # units per second

def log_structured(correlation_id, actor_id, step, outcome, latency_ms=0, **kwargs):
    """Emits a structured JSON log with the JSON_LOG: prefix."""
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": "dna_batch_parsing",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms
    }
    log_entry.update(kwargs)
    print(f"JSON_LOG: {json.dumps(log_entry)}")

def load_ledger(ledger_path):
    """Loads the structured ledger. Handles backward compatibility for flat ledgers."""
    default_state = {
        "system_heat": 0.0,
        "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and "ledger" in data:
                    return data
                else:
                    # Backward compatibility
                    default_state["ledger"] = data if isinstance(data, dict) else {}
                    return default_state
        except Exception:
            return default_state
    return default_state

def save_ledger(ledger_path, state):
    """Atomically saves the ledger state."""
    folder = os.path.dirname(ledger_path)
    ensure_folder(folder)
    with tempfile.TemporaryDirectory(dir=folder) as tmp_dir:
        tmp_path = os.path.join(tmp_dir, 'ledger.json')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)

def main(correlation_id="batch-default", actor_id="system"):
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

    state = load_ledger(ledger_path)
    ledger = state["ledger"]

    # Thermal Dissipation
    current_time = datetime.datetime.now(datetime.timezone.utc)
    last_time_str = state["last_processed_timestamp"].replace('Z', '+00:00')
    try:
        last_time = datetime.datetime.fromisoformat(last_time_str)
    except ValueError:
        # Fallback if the format was somehow broken
        last_time = current_time
    delta_seconds = (current_time - last_time).total_seconds()
    dissipation = delta_seconds * COOLING_RATE
    state["system_heat"] = max(0.0, state["system_heat"] - dissipation)

    # 1) Load existing JSON output
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
    lockout_occurred = False
    exception_during_loop = None

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                log_structured(correlation_id, actor_id, "idempotency_check", DNAStatus.SKIPPED.value,
                               dna=dna_str, system_heat=state["system_heat"])
                continue

            # Thermal Lockout Check
            if state["system_heat"] >= MAX_HEAT:
                log_structured(correlation_id, actor_id, "thermal_check", DNAStatus.REFUSED.value,
                               reason="Thermal Lockout", hint="Dissipation required. System indifferent to urgency.")
                lockout_occurred = True
                break

            start_time = time.time()
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

            except RuleParseError as e:
                parsed_json.append({'dna': dna_str, 'error': str(e)})
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR.value

            latency = int((time.time() - start_time) * 1000)
            state["system_heat"] += HEAT_PER_SEQ
            log_structured(correlation_id, actor_id, "parse_sequence", outcome,
                           latency_ms=latency, dna=dna_str, system_heat=state["system_heat"])

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            new_processed_count += 1
    except Exception as e:
        exception_during_loop = e
        raise
    finally:
        # Commit results if anything was processed
        if new_processed_count > 0:
            try:
                state["last_processed_timestamp"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                save_ledger(ledger_path, state)

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

                print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
            except Exception as e:
                # If we're already handling an exception (like RuleParseError or ThermalOverload),
                # we don't want to swallow it, but we also want to know if persistence failed.
                # However, if we were successful until now, we should raise PersistenceError.
                import sys
                # Check if an exception is currently being handled
                # sys.exc_info() returns (type, value, traceback)
                # In Python 3, we can also check if sys.exception() is None
                if exception_during_loop is None:
                    raise PersistenceError(f"Failed to commit results: {e}") from e
                else:
                    # We are already handling an exception from the loop
                    print(f"[CRITICAL] Persistence failed during error handling: {e}")

        if lockout_occurred:
            raise ThermalOverloadError("Thermal Lockout: Safety threshold exceeded.")

if __name__ == '__main__':
    main()
