#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
from enum import Enum
from dataclasses import dataclass
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

class TerminalOutcome(Enum):
    SUCCESS = "success"
    PARSE_ERROR = "error"
    SKIPPED = "skipped"

@dataclass
class DNAProcessingResult:
    dna: str
    rule: str
    parsed: dict
    outcome: TerminalOutcome
    error_msg: str = ""

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if not os.path.exists(input_path):
        return []
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

def load_json_safe(path):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json_safe(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def log_structured(correlation_id, chain_name, step, outcome, extra=None):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": str(correlation_id),
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome
    }
    if extra:
        log_entry.update(extra)
    print(f"[LOG] {json.dumps(log_entry)}")

def apply_thermal_noise(values):
    """Recursively scale all numeric values by 0.9."""
    if isinstance(values, dict):
        return {k: apply_thermal_noise(v) for k, v in values.items()}
    elif isinstance(values, (int, float)) and not isinstance(values, bool):
        return values * 0.9
    return values

def main(project_root=None):
    if project_root is None:
        project_root = os.getcwd()

    correlation_id = uuid.uuid4()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    # Load system state
    system_state = load_json_safe(state_path)
    system_heat = system_state.get('system_heat', 0.0)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
        dna_list = read_input_file(input_file)
        if not dna_list:
            return

        # Apply passive dissipation once per batch if there is work to do
        system_heat = max(0.0, float(system_heat) - 0.1)

        ledger = load_json_safe(ledger_path)

        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

        parsed_json = []
        if os.path.exists(json_output_path):
            try:
                with open(json_output_path, 'r', encoding='utf-8') as f:
                    parsed_json = json.load(f)
                    if not isinstance(parsed_json, list):
                        parsed_json = []
            except (json.JSONDecodeError, ValueError):
                parsed_json = []

        csv_rows = []
        all_flattened_keys = set()
        if os.path.exists(csv_output_path):
            with open(csv_output_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                all_flattened_keys = set(reader.fieldnames) if reader.fieldnames else set()
                csv_rows = list(reader)

        new_processed_count = 0

        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            # Thermal gain calculation
            heat_gain = 0.1 # base
            if dna_str.startswith("VOL"):
                try:
                    # Quick parse for heat calculation
                    amp_str = dna_str[3:7]
                    amp = int(amp_str)
                    if amp < 100:
                        heat_gain = -0.5
                    else:
                        heat_gain = 0.1 + (amp / 500.0)
                except:
                    pass

            if system_heat + heat_gain > 10.0:
                log_structured(correlation_id, "dna_batch_chain", "thermal_check", "refusal", {"current_heat": system_heat, "heat_gain": heat_gain})
                raise ThermalOverloadError(f"Thermal Overload: {system_heat + heat_gain:.2f} > 10.0")

            system_heat += heat_gain
            apply_noise = system_heat > 5.0
            if apply_noise:
                print(f"[SYSTEM] Thermal noise active. Output scaled for {dna_str}")

            try:
                result = calculator.parse(dna_str)
                parsed_values = result['values']
                if apply_noise:
                    parsed_values = apply_thermal_noise(parsed_values)

                outcome = TerminalOutcome.SUCCESS.value
                entry = {'dna': dna_str, 'rule': result['rule'], 'parsed': parsed_values}
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], parsed_values)
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

            except RuleParseError as e:
                outcome = TerminalOutcome.PARSE_ERROR.value
                parsed_json.append({'dna': dna_str, 'error': str(e)})
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            log_structured(correlation_id, "dna_batch_chain", "process_sequence", outcome, {"idempotency_key": idempotency_key})
            new_processed_count += 1

        if new_processed_count > 0:
            try:
                with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                    tmp_json = os.path.join(tmp_dir, 'output.json')
                    tmp_csv = os.path.join(tmp_dir, 'output.csv')

                    with open(tmp_json, 'w', encoding='utf-8') as f:
                        json.dump(parsed_json, f, indent=2)

                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            writer.writerow({k: row.get(k, '') for k in fieldnames})

                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

                save_json_safe(ledger_path, ledger)
            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e
            print(f"[OK] Processed {new_processed_count} new DNA strings.")

    finally:
        system_state['system_heat'] = system_heat
        save_json_safe(state_path, system_state)

if __name__ == '__main__':
    main()
