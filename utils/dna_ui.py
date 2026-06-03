#!/usr/bin/env python3
import os
import sys
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
    """Raised when system heat exceeds safety limits."""
    pass

THERMAL_MESSAGES = {
    "noise": "[WARN] Thermal Noise detected. Fidelity degradation active.",
    "refusal": "[FATAL] Thermal Overload. Core temperature exceeding safety limits.",
    "hint": "[INFO] Dissipate heat. Cooling cycles required."
}

def log_structured(correlation_id, chain_name, step, outcome, **kwargs):
    entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome
    }
    entry.update(kwargs)
    print(f"JSON_LOG: {json.dumps(entry)}")

def load_system_state(state_path):
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"system_heat": 0.0, "last_tick": time.time()}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def calculate_heat_delta(dna_str):
    # 0.3 for Volume (VOL prefix), 0.1 for others
    if dna_str.startswith("VOL"):
        return 0.3
    return 0.1

def apply_thermal_noise(values):
    """Recursively scale numeric values (excluding booleans) by 0.9."""
    if isinstance(values, dict):
        return {k: apply_thermal_noise(v) for k, v in values.items()}
    elif isinstance(values, (int, float)) and not isinstance(values, bool):
        return values * 0.9
    return values

def calculate_cooling(state):
    now = time.time()
    elapsed = now - state["last_tick"]
    # 0.0083 units/sec ~= 0.5 units/min
    cooling_rate = 0.0083
    reduction = elapsed * cooling_rate
    new_heat = max(0.0, state["system_heat"] - reduction)
    return new_heat, now

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

def main(correlation_id=None):
    if correlation_id is None:
        import uuid
        correlation_id = str(uuid.uuid4())

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
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
        # Apply cooling even if idle
        state = load_system_state(state_path)
        new_heat, now = calculate_cooling(state)
        state["system_heat"] = new_heat
        state["last_tick"] = now
        save_system_state(state_path, state)
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)
    state = load_system_state(state_path)

    # Initial cooling cycle
    new_heat, now = calculate_cooling(state)
    state["system_heat"] = new_heat
    state["last_tick"] = now

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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_structured(correlation_id, "dna_batch", "dedupe", "skipped", key=idempotency_key, dedupe_hit=True)
            continue

        log_structured(correlation_id, "dna_batch", "dedupe", "processing", key=idempotency_key, dedupe_hit=False)

        try:
            # Heat management
            heat_delta = calculate_heat_delta(dna_str)
            if state["system_heat"] + heat_delta > 10.0:
                print(THERMAL_MESSAGES["refusal"])
                print(THERMAL_MESSAGES["hint"])
                log_structured(correlation_id, "dna_batch", "thermal_check", "refused", heat=state["system_heat"], delta=heat_delta)
                # Persist heat before failing
                state["system_heat"] += heat_delta
                save_system_state(state_path, state)
                raise ThermalOverloadError(f"System heat {state['system_heat']:.2f} exceeds limit")

            state["system_heat"] += heat_delta

            result = calculator.parse(dna_str)
            parsed_values = result['values']

            if state["system_heat"] > 7.0:
                print(THERMAL_MESSAGES["noise"])
                log_structured(correlation_id, "dna_batch", "thermal_noise", "active", heat=state["system_heat"])
                parsed_values = apply_thermal_noise(parsed_values)

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': parsed_values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], parsed_values)
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

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
            outcome = f"error: {str(e)}"
        except ThermalOverloadError:
            # Do NOT update ledger; we want this retried after cooling
            # But we must stop processing more items in this batch
            break

        # Update ledger for success or parse error
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
        tmp_state = os.path.join(tmp_dir, 'state.json')

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

            # 3) Write Ledger and State
            # We must finalize ledger entries here correctly.
            # Actually, let's fix the ledger update logic to be cleaner.

            with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                json.dump(ledger, lf, indent=2)
                lf.flush()
                os.fsync(lf.fileno())

            with open(tmp_state, 'w', encoding='utf-8') as sf:
                json.dump(state, sf, indent=2)
                sf.flush()
                os.fsync(sf.fileno())

            # 4) Atomic rename (commit)
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)
            os.replace(tmp_state, state_path)

        except Exception as e:
            raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Attempted {len(dna_list)} DNA strings.")
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
