#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Thermal Fatigue System Constants ---
MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE_PER_SEC = 0.01

MSG_CONSEQUENCE = "System heat increasing. Mechanical fatigue imminent."
MSG_REFUSAL = "Thermal overload. Safety lockout engaged. Cooling required."
MSG_HINT = "Wait for thermal dissipation or reduce batch density."

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

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    PROCESSING = "processing"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when the system exceeds MAX_HEAT."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def load_ledger(ledger_path):
    """
    Loads the structured ledger state.
    Handles migration from legacy flat-dict ledger if necessary.
    """
    default_state = {
        "system_heat": 0.0,
        "last_processed_timestamp": 0.0,
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Migration: if data is a flat dict, it's the old ledger
                if isinstance(data, dict) and "ledger" not in data:
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": 0.0,
                        "ledger": data
                    }
                return data
        except Exception:
            return default_state
    return default_state

def save_ledger(ledger_path, state):
    """Saves the full structured state (heat + ledger)."""
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def log_structured(step, outcome, details=None):
    """Emits a structured JSON log entry with a prefix."""
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "step": step,
        "outcome": outcome
    }
    if details:
        log_entry.update(details)
    print(f"JSON_LOG: {json.dumps(log_entry)}")

def main():
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

    full_state = load_ledger(ledger_path)
    ledger = full_state.get("ledger", {})
    system_heat = full_state.get("system_heat", 0.0)
    last_ts = full_state.get("last_processed_timestamp", 0.0)

    # Apply cooling
    now = time.time()
    if last_ts > 0:
        elapsed = now - last_ts
        cooling = elapsed * COOLING_RATE_PER_SEC
        system_heat = max(0.0, system_heat - cooling)

    # Load existing results
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

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                log_structured("batch_process", DNAStatus.SKIPPED.value, {"dna": dna_str, "reason": "idempotency_hit"})
                continue

            # Thermal Check
            if system_heat + HEAT_PER_ITEM > MAX_HEAT:
                print(f"[FATIGUE] {MSG_REFUSAL} {MSG_HINT}")
                log_structured("batch_process", "refused", {"dna": dna_str, "reason": "thermal_overload", "heat": system_heat})
                raise ThermalOverloadError(f"{MSG_REFUSAL} {MSG_HINT}")

            # Process
            outcome = DNAStatus.PROCESSING.value
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

                system_heat += HEAT_PER_ITEM
                print(f"[FATIGUE] {MSG_CONSEQUENCE} current_heat={system_heat:.2f}")

            except RuleParseError as e:
                parsed_json.append({'dna': dna_str, 'error': str(e)})
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR.value

            # Update ledger per item
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1
            log_structured("item_process", outcome, {"dna": dna_str, "heat": system_heat})

    except ThermalOverloadError:
        # Partial batch allowed
        pass

    finally:
        # ATOMIC WRITE PATTERN
        full_state["system_heat"] = system_heat
        full_state["last_processed_timestamp"] = time.time()
        full_state["ledger"] = ledger

        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                # 1) Write outputs
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
                    json.dump(full_state, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 2) Atomic renames
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                log_structured("persistence", "failure", {"error": str(e)})
                raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA strings. System heat: {system_heat:.2f}")

if __name__ == '__main__':
    main()
