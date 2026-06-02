#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# Thermal Fatigue Constants
COOLING_RATE = 0.0083 # units per second (~1 unit every 2 mins)
NOISE_THRESHOLD = 7.0
OVERLOAD_THRESHOLD = 10.0

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if not os.path.isfile(input_path):
        return dna_list
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
                return json.load(f)
        except Exception:
            pass
    return {"system_heat": 0.0, "last_run_timestamp": time.time()}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def calculate_heat_delta(result):
    """Calculate heat gain based on processed sequence."""
    base_gain = 0.1
    rule_penalty = 0.0
    if result.get('rule') == 'Volume':
        rule_penalty = 0.2
    return base_gain + rule_penalty

def apply_thermal_noise(data):
    """Recursively scale numeric values by 0.9 to simulate noise."""
    if isinstance(data, dict):
        return {k: apply_thermal_noise(v) for k, v in data.items()}
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        return data * 0.9
    return data

def log_structured(correlation_id, chain_name, step, outcome, **kwargs):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
    }
    log_entry.update(kwargs)
    print(f"JSON_LOG: {json.dumps(log_entry)}")

def main(correlation_id="direct-call"):
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        # Still apply cooling if the file is missing but we're called
        system_state = load_system_state(state_path)
        now = time.time()
        elapsed = now - system_state.get("last_run_timestamp", now)
        cooling = elapsed * COOLING_RATE
        system_state["system_heat"] = max(0.0, system_state["system_heat"] - cooling)
        system_state["last_run_timestamp"] = now
        save_system_state(state_path, system_state)
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
    system_state = load_system_state(state_path)

    # Apply cooling
    now = time.time()
    elapsed = now - system_state.get("last_run_timestamp", now)
    cooling = elapsed * COOLING_RATE
    system_state["system_heat"] = max(0.0, system_state["system_heat"] - cooling)
    system_state["last_run_timestamp"] = now

    # Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                data = json.load(jf)
                if isinstance(data, list):
                    parsed_json = data
        except Exception:
            pass

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
    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                log_structured(correlation_id, "dna-batch", "dedupe", "skipped", idempotency_key=idempotency_key)
                continue

            try:
                # Preview heat impact
                # We need to parse to know the rule, but we check heat before "committing"
                # For simplicity in this minimal rule, we parse first
                result = calculator.parse(dna_str)
                heat_gain = calculate_heat_delta(result)

                if system_state["system_heat"] + heat_gain > OVERLOAD_THRESHOLD:
                    system_state["system_heat"] += heat_gain # Record the heat that broke it
                    save_system_state(state_path, system_state)
                    log_structured(correlation_id, "dna-batch", "thermal-check", "refusal",
                                   heat=system_state["system_heat"], threshold=OVERLOAD_THRESHOLD)
                    raise ThermalOverloadError("[FATAL] Thermal Overload. Core temperature exceeding safety limits.")

                system_state["system_heat"] += heat_gain

                final_values = result['values']
                if system_state["system_heat"] > NOISE_THRESHOLD:
                    final_values = apply_thermal_noise(final_values)
                    log_structured(correlation_id, "dna-batch", "thermal-noise", "applied", heat=system_state["system_heat"])

                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': final_values,
                    'system_heat': system_state["system_heat"]
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], final_values)
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                flat['system_heat'] = f"{system_state['system_heat']:.4f}"
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"

            except RuleParseError as e:
                parsed_json.append({'dna': dna_str, 'error': str(e)})
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = f"error: {str(e)}"

            except ThermalOverloadError:
                raise

            # Update ledger entry in memory
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1
            log_structured(correlation_id, "dna-batch", "process-item", outcome, dna=dna_str)

    except ThermalOverloadError:
        # We stop processing but we still want to save what we did so far (atomicity)
        pass

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_state = os.path.join(tmp_dir, 'state.json')

            try:
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush(); os.fsync(jf.fileno())

                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush(); os.fsync(cf.fileno())

                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush(); os.fsync(lf.fileno())

                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump(system_state, sf, indent=2)
                    sf.flush(); os.fsync(sf.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, state_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

        log_structured(correlation_id, "dna-batch", "batch-complete", "success",
                       new_items=new_processed_count, total_heat=system_state["system_heat"])
    else:
        # Still save system state if cooling occurred
        save_system_state(state_path, system_state)
        print("[OK] No new DNA strings to process.")

    # Re-raise thermal error if it happened so caller knows why we stopped
    # We check if it was raised during the loop
    # In a real impl we might use a flag
    # but for now let's just re-raise if heat > 10
    if system_state["system_heat"] > OVERLOAD_THRESHOLD:
        raise ThermalOverloadError("[FATAL] Thermal Overload. Core temperature exceeding safety limits.")

if __name__ == '__main__':
    main()
