#!/usr/bin/env python3
import os
import json
import csv
import time
import enum
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

def log_structured(step, outcome, correlation_id="manual", chain_name="dna_batch", actor_id="system", **kwargs):
    log_data = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "actor_id": actor_id,
        **kwargs
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def apply_thermal_noise(values):
    """
    Recursively scale numeric leaf values by 0.9 if noise is active.
    Excludes booleans or non-numeric types.
    """
    if isinstance(values, dict):
        return {k: apply_thermal_noise(v) for k, v in values.items()}
    elif isinstance(values, (int, float)) and not isinstance(values, bool):
        # We use a fixed factor of 0.9 as defined in the plan
        return values * 0.9
    else:
        return values

def calculate_heat_delta(result):
    """
    0.1 base heat gain for any sequence.
    VOL (Volume) sequences add +0.2 extra (total 0.3).
    """
    delta = 0.1
    if result.get('rule') == 'Volume':
        delta += 0.2
    return delta

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
    """Raised when system heat exceeds MAX_HEAT."""
    pass

class DNAStatus(Enum):
    SUCCESS = "success"
    PARSE_ERROR = "error"
    SKIPPED = "skipped"
    PROCESSING = "processing"

MAX_HEAT = 10.0
NOISE_THRESHOLD = 7.0
COOLING_RATE = 0.0083  # units per second

THERMAL_MESSAGES = {
    "consequence": "Data fidelity degraded. Hardware thermal fatigue detected.",
    "refusal": "Hardware refusal. Thermal overload limit exceeded.",
    "hint": "Allow system to cool before attempting further processing."
}
def load_ledger(ledger_path):
    """
    Returns a state dict: { "system_heat": float, "last_processed_timestamp": float, "ledger": dict }.
    Handles legacy ledger format (flat dict).
    """
    default_state = {
        "system_heat": 0.0,
        "last_processed_timestamp": time.time(),
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # If data is a flat dict, it's a legacy ledger
                if isinstance(data, dict):
                    if "ledger" in data and "system_heat" in data:
                        return data
                    else:
                        # Migrate legacy: data is the ledger
                        new_state = default_state.copy()
                        new_state["ledger"] = data
                        return new_state
        except Exception:
            pass
    return default_state

def save_ledger(ledger_path, state):
    """
    Saves the entire state (heat, timestamp, ledger).
    """
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Load state (includes ledger)
    state = load_ledger(ledger_path)
    old_heat = state["system_heat"]

    # 0) Apply Cooling
    now = time.time()
    elapsed = now - state["last_processed_timestamp"]
    if elapsed > 0:
        cooling_amount = elapsed * COOLING_RATE
        state["system_heat"] = max(0.0, state["system_heat"] - cooling_amount)
        state["last_processed_timestamp"] = now # Mark that we've cooled up to now
        if cooling_amount > 0.01:
            log_structured("cooling", "success",
                           heat_before=round(old_heat, 2),
                           heat_after=round(state["system_heat"], 2),
                           elapsed_sec=round(elapsed, 1),
                           message=f"System cooled by {round(cooling_amount, 2)} units.")

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        dna_list = []

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
    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in state['ledger']:
                log_structured("dedupe", "skipped", idempotency_key=idempotency_key, dedupe_hit=True)
                continue

            # Pre-calculate thermal cost
            temp_gain = 0.1
            if dna_str.startswith('VOL'):
                temp_gain = 0.3

            if state["system_heat"] + temp_gain > MAX_HEAT:
                log_structured("thermal_check", "refusal",
                               current_heat=round(state["system_heat"], 2),
                               limit=MAX_HEAT,
                               message=THERMAL_MESSAGES["refusal"],
                               hint=THERMAL_MESSAGES["hint"])
                raise ThermalOverloadError(THERMAL_MESSAGES["refusal"])

            log_structured("parse", "processing", idempotency_key=idempotency_key, dedupe_hit=False)

            try:
                result = calculator.parse(dna_str)
                values = result['values']

                # Apply noise if hot
                if state["system_heat"] > NOISE_THRESHOLD:
                    values = apply_thermal_noise(values)
                    log_structured("signal", "degraded",
                                   current_heat=round(state["system_heat"], 2),
                                   message=THERMAL_MESSAGES["consequence"])

                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': values
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], values)
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                outcome = DNAStatus.SUCCESS.value
                # Update heat
                state["system_heat"] += calculate_heat_delta(result)

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.PARSE_ERROR.value
                # Still adds base heat for trying
                state["system_heat"] += 0.1

            state['ledger'][idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            state["last_processed_timestamp"] = time.time()
            new_processed_count += 1

    except ThermalOverloadError:
        # We stop the batch but we still want to save what we did so far
        pass

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)

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

            # 3) Write Ledger state to temp
            with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                json.dump(state, lf, indent=2)
                lf.flush()
                os.fsync(lf.fileno())

            # 4) Atomic rename (commit)
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)

        except Exception as e:
            raise PersistenceError("Failed to write output files atomically") from e

    if new_processed_count > 0 or state["system_heat"] != old_heat:
        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(state['ledger'])}")
        print(f"     Heat: {round(state['system_heat'], 2)}")
    else:
        if not dna_list:
            print("[WARN] No DNA strings found in toSequence.txt")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
