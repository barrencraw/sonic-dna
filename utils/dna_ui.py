#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    NO_NEW_DNA = "NO_NEW_DNA"

def log_observability(step, outcome, data=None, correlation_id=None):
    payload = {
        "correlation_id": correlation_id or "N/A",
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "timestamp": time.time()
    }
    if data:
        payload.update(data)
    print(f"| TELEMETRY | {json.dumps(payload)}")

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
    """Raised when system heat is too high to process certain DNA types."""
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

def load_system_state(path):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"system_heat": 0.0}

def save_system_state(path, state):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main(data_dir=None):
    correlation_id = str(uuid.uuid4())
    log_observability("BATCH_START", Outcome.START, correlation_id=correlation_id)

    # Determine file paths
    project_root = data_dir if data_dir else os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability("INPUT_CHECK", Outcome.ERROR, {"error": "Input file not found"}, correlation_id=correlation_id)
        log_observability("BATCH_END", Outcome.END, correlation_id=correlation_id)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability("INIT_CALCULATOR", Outcome.ERROR, {"error": str(e)}, correlation_id=correlation_id)
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("READ_INPUT", Outcome.ERROR, {"error": str(e)}, correlation_id=correlation_id)
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability("BATCH_END", Outcome.END, {"msg": "No DNA strings found"}, correlation_id=correlation_id)
        return

    # Fatigue System: Natural Cooling
    state = load_system_state(state_path)
    old_heat = state["system_heat"]
    state["system_heat"] = max(0.0, state["system_heat"] - 1.0)
    # Save cooling state early so it's reflected even if all DNA are skipped
    save_system_state(state_path, state)
    log_observability("NATURAL_COOLING", Outcome.SUCCESS, {"old_heat": old_heat, "new_heat": state["system_heat"]}, correlation_id=correlation_id)

    ledger = load_ledger(ledger_path)

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

    new_processed_count = 0
    errors_count = 0

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability("PROCESS_ITEM", Outcome.SKIPPED, {"dna": dna_str, "reason": "idempotency_hit"}, correlation_id=correlation_id)
            continue

        log_observability("PROCESS_ITEM", Outcome.PROCESSING, {"dna": dna_str}, correlation_id=correlation_id)

        try:
            # Fatigue Logic: Clarity refusal
            if dna_str.startswith("CLA") and state["system_heat"] > 10.0:
                raise ThermalOverloadError(f"System heat ({state['system_heat']:.2f}) too high for Clarity parsing")

            result = calculator.parse(dna_str)

            # Fatigue Logic: Penalties and Heat Gain
            if result['rule'] == 'Volume':
                # VOL089... level is 'level' subvar
                amp = result['values'].get('level', 0)
                heat_gain = amp / 100.0
                state["system_heat"] += heat_gain
                log_observability("FATIGUE_UPDATE", Outcome.SUCCESS, {"dna": dna_str, "heat_gain": heat_gain, "total_heat": state["system_heat"]}, correlation_id=correlation_id)

            elif result['rule'] == 'Clarity':
                if state["system_heat"] > 0:
                    # Penalty: decrease noise_floor (making it less negative, e.g. -90 to -85)
                    # noise_floor is {'sign': 'N', 'value': 90}
                    heat_int = int(state["system_heat"])
                    old_nf = result['values']['noise_floor']['value']
                    result['values']['noise_floor']['value'] = max(0, old_nf - heat_int)

                    # Penalty: increase THD
                    old_thd = result['values']['thd']
                    result['values']['thd'] = min(1000, old_thd + (heat_int * 10))

                    log_observability("CONSEQUENCE_APPLIED", Outcome.SUCCESS, {
                        "dna": dna_str,
                        "heat": state["system_heat"],
                        "noise_floor_penalty": heat_int,
                        "thd_penalty": heat_int * 10
                    }, correlation_id=correlation_id)

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
            outcome = Outcome.SUCCESS

        except ThermalOverloadError as e:
            log_observability("PROCESS_ITEM", Outcome.ERROR, {"dna": dna_str, "error": str(e), "refusal": True}, correlation_id=correlation_id)
            # Refusal doesn't record to ledger or outputs (to allow retry when cooled)
            print(f"| REFUSAL_REASON | {str(e)}")
            print(f"| NEXT_ACTION_HINT | Wait for system cooling or process non-Clarity DNA.")
            errors_count += 1
            continue

        except RuleParseError as e:
            log_observability("PROCESS_ITEM", Outcome.ERROR, {"dna": dna_str, "error": str(e)}, correlation_id=correlation_id)
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR
            errors_count += 1

        except Exception as e:
            log_observability("PROCESS_ITEM", Outcome.ERROR, {"dna": dna_str, "error": str(e)}, correlation_id=correlation_id)
            raise e

        # Update ledger
        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value, # Now matches Outcome enum value (UPPERCASE)
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    # Final batch outcome
    if new_processed_count == 0:
        batch_outcome = Outcome.NO_NEW_DNA
    elif errors_count == 0:
        batch_outcome = Outcome.SUCCESS
    elif new_processed_count > errors_count:
        batch_outcome = Outcome.PARTIAL_SUCCESS
    else:
        batch_outcome = Outcome.ERROR

    # ATOMIC COMMIT
    if new_processed_count > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                save_system_state(state_path, state)

            except Exception as e:
                log_observability("COMMIT", Outcome.ERROR, {"error": str(e)}, correlation_id=correlation_id)
                raise PersistenceError("Failed to write output files atomically") from e
    else:
        # If nothing new processed, still save system state (e.g. for cooling)
        save_system_state(state_path, state)

    log_observability("BATCH_END", batch_outcome, {
        "processed": new_processed_count,
        "errors": errors_count,
        "final_heat": state["system_heat"]
    }, correlation_id=correlation_id)

    print(f"[OK] Batch complete: {batch_outcome.value}")
    if new_processed_count > 0:
        print(f"     Processed {new_processed_count} new DNA strings.")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
