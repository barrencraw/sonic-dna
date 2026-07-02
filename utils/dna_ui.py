#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Constants & Enums ---
HEAT_INCREMENT = 5.0
DISSIPATION_RATE = 0.5
LOCKOUT_THRESHOLD = 100.0

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# --- Exceptions ---
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
    """Raised when system is in thermal lockout."""
    pass

# --- Utilities ---
def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def log_structured(message, level="INFO", **kwargs):
    """Emits a structured JSON log for systemic observability."""
    log_data = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "level": level,
        "message": message
    }
    log_data.update(kwargs)
    print(f"JSON_LOG: {json.dumps(log_data)}")

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
    """Loads ledger, system heat, and last processed timestamp."""
    default_state = {
        "system_heat": 0.0,
        "last_processed_timestamp": time.time(),
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Ensure all keys exist
                for key in default_state:
                    if key not in data:
                        data[key] = default_state[key]
                return data
        except Exception:
            return default_state
    return default_state

def save_ledger(ledger_path, state):
    """Saves the full state to the ledger file."""
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main(correlation_id="batch-default", actor_id="system"):
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(f"Input file not found: {input_file}", level="ERROR")
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
        log_structured("No DNA strings found in toSequence.txt", level="WARN")
        return

    state = load_ledger(ledger_path)
    ledger = state["ledger"]
    system_heat = state["system_heat"]
    last_ts = state["last_processed_timestamp"]

    # Calculate dissipation
    now = time.time()
    elapsed = now - last_ts
    system_heat = max(0.0, system_heat - (elapsed * DISSIPATION_RATE))

    log_structured("Batch processing started",
                   correlation_id=correlation_id,
                   actor_id=actor_id,
                   initial_heat=system_heat)

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
    items_refused_in_this_run = 0
    any_item_attempted = False

    for dna_str in dna_list:
        idempotency_key = dna_str
        item_start_time = time.time()

        if idempotency_key in ledger:
            terminal_outcome = ledger[idempotency_key]['terminal_outcome']
            # Only skip if it was a final SUCCESS.
            # If it was REFUSED or ERROR, we might want to retry.
            if terminal_outcome == DNAStatus.SUCCESS.value:
                log_structured("Deduplication hit",
                               idempotency_key=idempotency_key,
                               outcome=DNAStatus.SKIPPED.value,
                               correlation_id=correlation_id)
                continue

        any_item_attempted = True
        # Thermal Check
        if system_heat > LOCKOUT_THRESHOLD:
            outcome = DNAStatus.REFUSED.value
            items_refused_in_this_run += 1
            log_structured("Thermal Lockout",
                           level="WARN",
                           idempotency_key=idempotency_key,
                           outcome=outcome,
                           heat=system_heat,
                           hint="Dissipation required. System indifferent to urgency.")
        else:
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
                system_heat += HEAT_INCREMENT
                log_structured("Heat Accumulation", heat=system_heat, increment=HEAT_INCREMENT)

            except RuleParseError as e:
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e)
                })
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                outcome = DNAStatus.ERROR.value
                system_heat += HEAT_INCREMENT
                log_structured("Heat Accumulation", heat=system_heat, increment=HEAT_INCREMENT)
            except Exception as e:
                outcome = DNAStatus.ERROR.value
                log_structured("Unexpected error during parsing", level="ERROR", error=str(e))

        # Update ledger and telemetry for this item
        latency_ms = int((time.time() - item_start_time) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }

        log_structured("Item processed",
                       idempotency_key=idempotency_key,
                       outcome=outcome,
                       latency_ms=latency_ms,
                       correlation_id=correlation_id)

        if outcome != DNAStatus.REFUSED.value:
            new_processed_count += 1

    # Atomic write phase
    if any_item_attempted:
        state["system_heat"] = system_heat
        state["last_processed_timestamp"] = time.time()

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

                # Commit
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    log_structured("Batch processing complete",
                   new_items=new_processed_count,
                   final_heat=system_heat,
                   correlation_id=correlation_id)

    if items_refused_in_this_run > 0:
        raise ThermalOverloadError(f"System overheated. {items_refused_in_this_run} items deferred.")

if __name__ == '__main__':
    main()
