#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from utils.dna_calculator import DNACalculator, RuleParseError

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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def log_structured(timestamp, correlation_id, chain_name, step, outcome_val, actor_id, extra=None):
    log_entry = {
        "timestamp": timestamp,
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome_val,
        "actor_id": actor_id
    }
    if extra:
        log_entry.update(extra)
    print(json.dumps(log_entry))

def apply_thermal_noise(data):
    """Recursively scale numeric leaves by 0.9."""
    if isinstance(data, dict):
        return {k: apply_thermal_noise(v) for k, v in data.items()}
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        return data * 0.9
    return data

def main(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    # Determine file paths
    project_root = os.getcwd()
    data_folder = os.path.join(project_root, 'data')
    raw_folder = os.path.join(data_folder, 'raw')
    output_folder = os.path.join(data_folder, 'output')
    ledger_path = os.path.join(data_folder, 'processed_ledger.json')
    state_path = os.path.join(data_folder, 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

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

    # Load system state (heat)
    system_heat = 0.0
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r') as sf:
                state = json.load(sf)
                system_heat = float(state.get('system_heat', 0.0))
        except Exception:
            pass

    # Passive dissipation: -0.1 per batch if NOT empty
    if dna_list:
        system_heat = max(0.0, system_heat - 0.1)

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
    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            outcome = "unknown"
            try:
                result = calculator.parse(dna_str)

                # Fatigue calculation for Volume rule
                heat_gain = 0.0
                if result['rule'] == 'Volume':
                    amp = result['values'].get('amp', 0)
                    if amp < 100:
                        # Cooling cycle
                        heat_gain = -0.5
                    else:
                        # Standard heat gain
                        heat_gain = 0.1 + (amp / 500.0)

                # Check Overload
                if system_heat + heat_gain > 10.0:
                    print("[FATAL] Thermal Overload. Core temperature exceeding safety limits.")
                    print("[INFO] Dissipate heat. Cooling cycles required.")
                    raise ThermalOverloadError("Thermal Overload")

                # Apply Noise if heat > 5.0
                if system_heat + heat_gain > 5.0:
                    print("[WARN] Thermal Noise detected. Fidelity degradation active.")
                    result['values'] = apply_thermal_noise(result['values'])

                # Update system heat
                system_heat = max(0.0, system_heat + heat_gain)

                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values'],
                    'system_heat': round(system_heat, 2)
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                flat['system_heat'] = round(system_heat, 2)
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e)
                })
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = f"error: {str(e)}"

            # Update ledger within loop
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            log_structured(
                time.strftime('%Y-%m-%d %H:%M:%S'),
                correlation_id,
                "dna_batch_chain",
                "process_sequence",
                outcome,
                "batch_processor",
                {"idempotency_key": idempotency_key}
            )
            new_processed_count += 1

    except ThermalOverloadError:
        # Re-raise to be caught by watcher/main
        raise
    finally:
        # Save system state even if error occurred (but after processing loop finishes or hits FATAL)
        with open(state_path, 'w') as sf:
            json.dump({'system_heat': round(system_heat, 2)}, sf)

        if new_processed_count > 0:
            # ATOMIC WRITE PATTERN
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

                except Exception as e:
                    raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    if new_processed_count > 0:
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
