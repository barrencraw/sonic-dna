#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    NO_NEW_DNA = "NO_NEW_DNA"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"

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
    """Raised when system heat exceeds safe thresholds."""
    pass

def log_observability(outcome, correlation_id=None, **kwargs):
    """
    Outputs pipe-delimited telemetry format.
    | TELEMETRY | {json}
    """
    telemetry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "correlation_id": correlation_id or "N/A",
    }
    telemetry.update(kwargs)
    print(f"| TELEMETRY | {json.dumps(telemetry)}")

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

def load_system_state(state_path):
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
                return state.get("system_heat", 0.0)
        except Exception:
            return 0.0
    return 0.0

def save_system_state(state_path, heat):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump({"system_heat": heat}, f, indent=2)

def main(data_dir=None):
    correlation_id = str(uuid.uuid4())

    # Rules are always relative to this script's location (utils/dna_ui.py -> ../rules)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    rules_folder = os.path.join(os.path.dirname(script_dir), 'rules')

    # Data files are relative to data_dir or current working directory
    project_root = data_dir or os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')

    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(Outcome.END, correlation_id, reason="Input file not found")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(Outcome.END, correlation_id, reason="No DNA strings found")
        return

    log_observability(Outcome.START, correlation_id, count=len(dna_list))

    ledger = load_ledger(ledger_path)
    system_heat = load_system_state(state_path)

    # Natural cooling
    system_heat = max(0.0, system_heat - 1.0)

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
    success_count = 0
    error_count = 0

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability(Outcome.SKIPPED, correlation_id, dna=dna_str, reason="idempotency_hit")
            continue

        log_observability(Outcome.PROCESSING, correlation_id, dna=dna_str)

        error_msg = None
        flattened_vals = {}
        try:
            # FATIGUE SYSTEM: Thermal Overload Check
            if dna_str.startswith("CLA") and system_heat > 10.0:
                raise ThermalOverloadError("System thermal overload. Clarity parsing inhibited.")

            result = calculator.parse(dna_str)

            # FATIGUE SYSTEM: Apply Penalty for Clarity
            if result['rule'] == "Clarity" and system_heat > 0.0:
                penalty = int(system_heat)
                # Raising floor: N090 -> N085 (90 -> 85)
                original = result['values']['noise_floor']['value']
                result['values']['noise_floor']['value'] = max(0, original - penalty)
                log_observability(Outcome.SUCCESS, correlation_id, dna=dna_str,
                                  CONSEQUENCE_APPLIED="Thermal noise floor degradation active.",
                                  NEXT_ACTION_HINT="Allow system to cool or process lower-amplitude sequences.")

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # FATIGUE SYSTEM: Heat Accumulation for Volume
            if result['rule'] == "Volume":
                system_heat += result['values']['amp'] / 100.0

            # Flatten for CSV
            flattened_vals = flatten_parsed(result['rule'], result['values'])
            flattened_vals['dna'] = dna_str
            flattened_vals['rule'] = result['rule']
            csv_rows.append(flattened_vals)
            all_flattened_keys.update(flattened_vals.keys())
            outcome = Outcome.SUCCESS
            success_count += 1

        except ThermalOverloadError as e:
            error_msg = str(e)
            log_observability(Outcome.ERROR, correlation_id, dna=dna_str,
                              REFUSAL_REASON=error_msg,
                              NEXT_ACTION_HINT="Allow system to cool or process lower-amplitude sequences.")
            parsed_json.append({
                'dna': dna_str,
                'error': error_msg
            })
            outcome = Outcome.ERROR
            error_count += 1
        except RuleParseError as e:
            error_msg = str(e)
            parsed_json.append({
                'dna': dna_str,
                'error': error_msg
            })
            flattened_vals = {'dna': dna_str, 'error': error_msg}
            csv_rows.append(flattened_vals)
            all_flattened_keys.update(flattened_vals.keys())
            outcome = Outcome.ERROR
            error_count += 1
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            outcome = Outcome.ERROR
            error_count += 1

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_observability(outcome, correlation_id, dna=dna_str, error=error_msg)
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    if new_processed_count > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                # 1) Write JSON output to temp
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) Write CSV output to temp
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Write Ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic renames (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    # Persist system state regardless of processed count if list was non-empty (for natural cooling)
    save_system_state(state_path, system_heat)

    final_batch_outcome = Outcome.SUCCESS
    if error_count > 0:
        final_batch_outcome = Outcome.PARTIAL_SUCCESS if success_count > 0 else Outcome.ERROR
    if new_processed_count == 0:
        final_batch_outcome = Outcome.NO_NEW_DNA

    log_observability(final_batch_outcome, correlation_id,
                      processed=new_processed_count,
                      successes=success_count,
                      errors=error_count,
                      system_heat=system_heat)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Heat: {system_heat:.2f}")

if __name__ == '__main__':
    main()
