#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from enum import Enum
from dataclasses import dataclass
from utils.dna_calculator import DNACalculator, RuleParseError

class TerminalOutcome(Enum):
    SUCCESS = "success"
    PARSE_ERROR = "parse_error"
    SKIPPED = "skipped"

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
    """Raised when system heat exceeds critical threshold."""
    pass

@dataclass
class DNAProcessingResult:
    dna: str
    outcome: TerminalOutcome
    error_message: str = None
    parsed_data: dict = None
    rule: str = None

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
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

def load_system_state(state_path):
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    try:
        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass

def apply_thermal_noise(data):
    """Recursively multiply numeric values by 0.9 if heat is high."""
    if isinstance(data, dict):
        return {k: apply_thermal_noise(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [apply_thermal_noise(v) for v in data]
    elif isinstance(data, (int, float)):
        return round(data * 0.9, 3)
    return data

def log_structured(step, outcome, latency_ms=0, dna=None, extra=None):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": "dna_batch_" + str(int(time.time())),
        "actor_id": "system",
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms
    }
    if dna:
        log_entry["idempotency_key"] = dna
    if extra:
        log_entry.update(extra)
    print(json.dumps(log_entry))

def main(project_root=None):
    if project_root is None:
        project_root = os.getcwd()

    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)
    ensure_folder(os.path.dirname(ledger_path))

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Load system state and apply passive dissipation
    system_state = load_system_state(state_path)
    system_heat = max(0.0, system_state.get("system_heat", 0.0) - 0.5)
    system_state["system_heat"] = round(system_heat, 2)

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules: {e}")

    dna_list = read_input_file(input_file)
    if not dna_list:
        # Still save state to persist dissipation
        save_system_state(state_path, system_state)
        return

    ledger = load_ledger(ledger_path)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as f:
                parsed_json = json.load(f)
        except Exception:
            pass

    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')
    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    csv_rows = list(reader)
        except Exception:
            pass

    new_processed_count = 0
    start_time_batch = time.time()

    for dna_str in dna_list:
        if dna_str in ledger:
            log_structured("processing_dna", "skipped", dna=dna_str, extra={"reason": "idempotency_hit"})
            continue

        # HEAT GAIN IS CALCULATED AT THE START OF PROCESSING TO AFFECT CURRENT ITEM
        # This ensures high heat immediately impacts the very first string if it pushes over threshold

        start_time_dna = time.time()
        try:
            result = calculator.parse(dna_str)
            parsed_values = result['values']

            # Heat gain (pre-calculate for checks)
            heat_gain = 0.1
            if result['rule'] == 'Volume':
                amp = parsed_values.get('amp', 0)
                heat_gain += (amp / 500.0)

            # Check Thermal Overload (Refusal happens if this item pushes it over)
            if (system_heat + heat_gain) > 10.0:
                print(f"[FATAL] Thermal Overload: {(system_heat + heat_gain):.2f} > 10.0. Refusing processing.")
                print("[INFO] Dissipate heat via low-amplitude cycles or wait for passive cooling.")
                raise ThermalOverloadError(f"System heat {(system_heat + heat_gain):.2f} too high.")

            # Apply Thermal Noise
            if (system_heat + heat_gain) > 5.0:
                print(f"[SYSTEM] Thermal noise active (Heat: {(system_heat + heat_gain):.2f}). Degrading precision.")
                parsed_values_to_save = apply_thermal_noise(parsed_values)
            else:
                parsed_values_to_save = parsed_values

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': parsed_values_to_save
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], parsed_values_to_save)
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = TerminalOutcome.SUCCESS
            error_msg = None

            # Heat gain is applied AFTER processing the DNA but using the heat calculated BEFORE the item
            system_heat = round(system_heat + heat_gain, 2)

        except (RuleParseError, ThermalOverloadError) as e:
            if isinstance(e, ThermalOverloadError):
                # We want to re-raise it if it's a thermal overload, BUT we must save the state first
                # Actually, the requirement is to STOP.
                # If we raise it here, it will exit the main() and skip atomic commit.
                # Let's save state before raising.
                # Use current system_heat which includes the item that pushed it over.
                system_state["system_heat"] = round(system_heat + heat_gain, 2)
                save_system_state(state_path, system_state)
                raise

            error_msg = str(e)
            parsed_json.append({'dna': dna_str, 'error': error_msg})
            flat = {'dna': dna_str, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = TerminalOutcome.PARSE_ERROR

        latency = int((time.time() - start_time_dna) * 1000)
        ledger[dna_str] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_structured("processing_dna", outcome.value, latency_ms=latency, dna=dna_str)
        new_processed_count += 1

    system_state["system_heat"] = system_heat
    if new_processed_count > 0:
        # Atomic commit
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_state = os.path.join(tmp_dir, 'state.json')

            try:
                with open(tmp_json, 'w', encoding='utf-8') as f:
                    json.dump(parsed_json, f, indent=2)

                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        writer.writerow({k: row.get(k, '') for k in fieldnames})

                with open(tmp_ledger, 'w', encoding='utf-8') as f:
                    json.dump(ledger, f, indent=2)

                with open(tmp_state, 'w', encoding='utf-8') as f:
                    json.dump(system_state, f, indent=2)

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, state_path)
            except Exception as e:
                raise PersistenceError(f"Failed to commit batch results: {e}")
    else:
        # Just save system state if nothing else was processed
        save_system_state(state_path, system_state)

    total_latency = int((time.time() - start_time_batch) * 1000)
    log_structured("batch_complete", "success", latency_ms=total_latency, extra={"new_processed": new_processed_count, "system_heat": system_heat})

if __name__ == '__main__':
    main()
