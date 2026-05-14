#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Any, Dict
from utils.dna_calculator import DNACalculator, RuleParseError

class TerminalOutcome(Enum):
    SUCCESS = "SUCCESS"
    PARSE_ERROR = "PARSE_ERROR"
    SKIPPED = "SKIPPED"

@dataclass
class DNAProcessingResult:
    dna_sequence: str
    terminal_outcome: TerminalOutcome
    parsed_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    consequences: Dict[str, Any] = field(default_factory=dict)

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
    """Raised when system heat exceeds threshold."""
    pass

def log_structured(correlation_id: str, chain_name: str, step: str, outcome: str, latency_ms: int = 0, **kwargs):
    log_entry = {
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms
    }
    log_entry.update(kwargs)
    print(json.dumps(log_entry))

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
    """Recursively multiply numeric leaf values by 0.9, rounded to 3 decimal places."""
    if isinstance(data, dict):
        return {k: apply_thermal_noise(v) for k, v in data.items()}
    elif isinstance(data, (int, float)):
        return round(data * 0.9, 3)
    return data

def main():
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
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)
    system_state = load_system_state(state_path)

    # Passive cooling
    system_state["system_heat"] = max(0.0, round(system_state["system_heat"] - 0.5, 2))

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

    correlation_id = str(int(time.time()))
    new_processed_count = 0

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                log_structured(correlation_id, "dna_batch_chain", "idempotency_check", "SUCCESS",
                               idempotency_key=idempotency_key, dedupe_hit=True)
                continue

            # Thermal Overload Check
            if system_state["system_heat"] > 10.0:
                log_structured(correlation_id, "dna_batch_chain", "thermal_check", "REFUSAL",
                               REFUSAL_REASON="System heat critical (exceeds 10.0)",
                               NEXT_ACTION_HINT="Cease processing until thermal dissipation occurs")
                raise ThermalOverloadError(f"System heat {system_state['system_heat']} exceeds threshold 10.0")

            try:
                result = calculator.parse(dna_str)
                parsed_values = result['values']

                # Consequence Calculation: Volume Heat Gain
                consequences = {}
                if result['rule'] == "Volume":
                    amp = parsed_values.get('amp', 0)
                    heat_gain = round(0.1 + (amp / 500.0), 2)
                    system_state["system_heat"] = round(system_state["system_heat"] + heat_gain, 2)
                    consequences["heat_gain"] = heat_gain
                    log_structured(correlation_id, "dna_batch_chain", "consequence_calculation", "SUCCESS",
                                   CONSEQUENCE_APPLIED=f"Thermal gain {heat_gain} from Volume processing",
                                   idempotency_key=idempotency_key)

                # Thermal Noise Application
                if system_state["system_heat"] > 5.0:
                    parsed_values = apply_thermal_noise(parsed_values)
                    log_structured(correlation_id, "dna_batch_chain", "thermal_noise", "SUCCESS",
                                   CONSEQUENCE_APPLIED="Thermal noise applied due to high heat (> 5.0)",
                                   idempotency_key=idempotency_key)

                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': parsed_values,
                    'consequences': consequences
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], parsed_values)
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = TerminalOutcome.SUCCESS.value

            except RuleParseError as e:
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e)
                })
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = TerminalOutcome.PARSE_ERROR.value

            # Update Ledger within loop
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1

            # ATOMIC WRITE PATTERN (Per-item commit):
            # 1. Write to a temporary directory
            # 2. Rename to final destination
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

                try:
                    # Write JSON
                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    # Write CSV
                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())

                    # Write Ledger
                    with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                        json.dump(ledger, lf, indent=2)
                        lf.flush()
                        os.fsync(lf.fileno())

                    # Atomic rename
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)
                    os.replace(tmp_ledger, ledger_path)

                except Exception as e:
                    raise PersistenceError("Failed to write output files atomically") from e

    finally:
        # Always save system state, even if a sequence fails or thermal overload occurs
        save_system_state(state_path, system_state)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
