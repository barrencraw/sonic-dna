#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
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

class DataIntegrityError(DNAProcessingError):
    """Raised if existing data files fail to load securely."""
    pass

class TerminalOutcome(Enum):
    SUCCESS = "SUCCESS"
    PARSE_ERROR = "PARSE_ERROR"
    SKIPPED = "SKIPPED"

@dataclass
class DNAProcessingResult:
    dna_sequence: str
    rule: str
    parsed: dict
    outcome: TerminalOutcome

def log_structured(chain_name, step, outcome_val, correlation_id, extra=None):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome_val,
        "correlation_id": str(correlation_id)
    }
    if extra:
        log_entry.update(extra)
    print(json.dumps(log_entry))

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads DNA strings from input_path.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_sequences = []
    if not os.path.exists(input_path):
        return dna_sequences
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_sequences.append(s)
    return dna_sequences

def flatten_parsed(rule_name, values_dict, parent_key=''):
    """
    Given nested values_dict, flatten into { 'rule.sub1.sub2': value, ... }.
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
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise PersistenceError(f"Failed to save ledger: {e}")

def load_system_state(state_path):
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"system_heat": 0.0}
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    try:
        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass # Best effort

def apply_thermal_noise(data):
    """
    Recursively scale all numeric values (int, float) by 0.9.
    Excludes booleans.
    """
    if isinstance(data, dict):
        return {k: apply_thermal_noise(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [apply_thermal_noise(v) for v in data]
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        return data * 0.9
    return data

def main(project_root=None, correlation_id=None):
    if project_root is None:
        project_root = os.getcwd()
    if correlation_id is None:
        correlation_id = uuid.uuid4()

    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    try:
        dna_sequences = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequences:
        return

    # Load systemic state
    state = load_system_state(state_path)
    system_heat = float(state.get("system_heat", 0.0))

    # Passive dissipation (only if we have items to process)
    system_heat = max(0.0, system_heat - 0.1)

    ledger = load_ledger(ledger_path)

    # Load existing outputs securely
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    raise DataIntegrityError("JSON output exists but is not a list")
        except Exception as e:
            if isinstance(e, DataIntegrityError): raise
            print(f"[WARN] Failed to load {json_output_path}, starting fresh: {e}")
            parsed_json = []

    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as cf:
                reader = csv.DictReader(cf)
                if reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    csv_rows = list(reader)
        except Exception as e:
            print(f"[WARN] Failed to load {csv_output_path}, starting fresh: {e}")
            csv_rows = []

    new_processed_count = 0
    outcome_val = TerminalOutcome.SKIPPED.value

    overload_error = None
    try:
        for dna_sequence in dna_sequences:
            idempotency_key = dna_sequence
            if idempotency_key in ledger:
                log_structured("dna_batch_chain", "deduplication", "SKIPPED", correlation_id, {"idempotency_key": idempotency_key})
                continue

            try:
                result = calculator.parse(dna_sequence)

                # Thermal Fatigue Logic
                heat_gain = 0.0
                if result['rule'] == 'Volume':
                    amp = result['values'].get('amp', 0)
                    if amp < 100:
                        heat_gain = -0.5 # Cooling cycle
                    else:
                        heat_gain = 0.1 + (amp / 500.0)

                if system_heat + heat_gain > 10.0:
                    log_structured("dna_batch_chain", "thermal_check", "FAIL", correlation_id, {"idempotency_key": idempotency_key, "heat": system_heat + heat_gain})
                    overload_error = ThermalOverloadError(f"Thermal Overload: {system_heat + heat_gain:.2f} exceeds safety limit 10.0")
                    break

                system_heat = max(0.0, system_heat + heat_gain)

                # Apply Noise if heat > 5.0
                if system_heat > 5.0:
                    print(f"[SYSTEM] Thermal noise active. Core temperature: {system_heat:.2f}")
                    log_structured("dna_batch_chain", "thermal_noise", "ACTIVE", correlation_id, {"heat": system_heat})
                    result['values'] = apply_thermal_noise(result['values'])

                entry = {
                    'dna': dna_sequence,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_sequence
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome_val = TerminalOutcome.SUCCESS.value

            except RuleParseError as e:
                parsed_json.append({'dna': dna_sequence, 'error': str(e)})
                flat = {'dna': dna_sequence, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome_val = TerminalOutcome.PARSE_ERROR.value

            # Update ledger within loop
            ledger[idempotency_key] = {
                'terminal_outcome': outcome_val.lower(),
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1
            log_structured("dna_batch_chain", "process_item", outcome_val, correlation_id, {"idempotency_key": idempotency_key})

        if new_processed_count > 0:
            # Atomic Write Block
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

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
                            writer.writerow({k: row.get(k, '') for k in fieldnames})
                        cf.flush()
                        os.fsync(cf.fileno())

                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)
                except Exception as e:
                    raise PersistenceError(f"Failed to write output files atomically: {e}")

            save_ledger(ledger_path, ledger)
            log_structured("dna_batch_chain", "batch_complete", "SUCCESS", correlation_id, {"processed_count": new_processed_count})

        if overload_error:
            raise overload_error

    finally:
        # Persist systemic state updates
        state["system_heat"] = system_heat
        save_system_state(state_path, state)

if __name__ == '__main__':
    main()
