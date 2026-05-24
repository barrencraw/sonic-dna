#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from dataclasses import dataclass
from utils.dna_calculator import DNACalculator, RuleParseError

class TerminalOutcome(Enum):
    SUCCESS = "SUCCESS"
    PARSE_ERROR = "PARSE_ERROR"
    SKIPPED = "SKIPPED"

@dataclass
class DNAProcessingResult:
    dna_sequence: str
    terminal_outcome: TerminalOutcome
    parsed_data: dict = None
    error_message: str = None

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class DataIntegrityError(DNAProcessingError):
    """Raised if existing data files fail to load securely."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system heat exceeds safety limits."""
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    raise DataIntegrityError(f"Ledger at {ledger_path} is not a dictionary")
                return data
        except json.JSONDecodeError:
            # For empty or corrupt files, return empty dict or raise if strictness desired
            return {}
        except Exception as e:
            if isinstance(e, DataIntegrityError): raise e
            raise DataIntegrityError(f"Failed to load ledger at {ledger_path}: {e}")
    return {}

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def log_structured(correlation_id, idempotency_key, step, outcome_val, extras=None):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": str(correlation_id),
        "idempotency_key": idempotency_key,
        "step": step,
        "outcome": outcome_val
    }
    if extras:
        log_entry.update(extras)
    print(json.dumps(log_entry))

def apply_thermal_noise(data):
    """Recursively apply 0.9 noise factor to all numeric values."""
    if isinstance(data, dict):
        return {k: apply_thermal_noise(v) for k, v in data.items()}
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        return data * 0.9
    return data

def main(correlation_id=None, project_root=None):
    if correlation_id is None:
        correlation_id = uuid.uuid4()
    if project_root is None:
        project_root = os.getcwd()

    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)
    ensure_folder(os.path.dirname(state_path))

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Load system state (Thermal Fatigue)
    system_heat = 0.0
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r') as sf:
                state = json.load(sf)
                system_heat = float(state.get('system_heat', 0.0))
        except Exception:
            system_heat = 0.0

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        return

    # Passive dissipation (applied once per batch)
    system_heat = max(0.0, system_heat - 0.1)

    ledger = load_ledger(ledger_path)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    raise DataIntegrityError("JSON output is not a list")
        except Exception as e:
            raise DataIntegrityError(f"Failed to load JSON output securely: {e}")

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
        except Exception as e:
            raise DataIntegrityError(f"Failed to load CSV output securely: {e}")

    new_processed_count = 0
    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                log_structured(correlation_id, idempotency_key, "batch_check", TerminalOutcome.SKIPPED.value)
                continue

            log_structured(correlation_id, idempotency_key, "batch_process", "STARTED")

            # Thermal Fatigue Logic
            heat_gain = 0.2 # Default gain per sequence
            if dna_str.startswith("VOL"):
                # Example: VOL gain based on amplitude (stubbed logic)
                heat_gain = 0.3

            if system_heat + heat_gain > 10.0:
                raise ThermalOverloadError("System heat safety limit (10.0) exceeded.")

            system_heat += heat_gain

            try:
                result = calculator.parse(dna_str)

                # Apply noise if hot
                if system_heat > 5.0:
                    result['values'] = apply_thermal_noise(result['values'])

                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                outcome = TerminalOutcome.SUCCESS
                log_structured(correlation_id, idempotency_key, "batch_process", outcome.value)

            except RuleParseError as e:
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e)
                })
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                outcome = TerminalOutcome.PARSE_ERROR
                log_structured(correlation_id, idempotency_key, "batch_process", outcome.value, {"error": str(e)})

            ledger[idempotency_key] = {
                'terminal_outcome': outcome.value,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'correlation_id': str(correlation_id)
            }
            new_processed_count += 1

    except ThermalOverloadError as e:
        print(f"[FATAL] Thermal Overload: {e}")
        print("[INFO] Dissipate heat by waiting or processing cooling cycles.")
        # We still commit what we processed successfully so far
        pass

    if new_processed_count > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_state = os.path.join(tmp_dir, 'system_state.json')

            try:
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

                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump({'system_heat': system_heat}, sf, indent=2)
                    sf.flush()
                    os.fsync(sf.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, state_path)

            except Exception as e:
                raise PersistenceError(f"Failed to write output files atomically: {e}")

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
