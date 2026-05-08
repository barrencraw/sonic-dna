#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from typing import Optional
from utils.dna_calculator import DNACalculator, RuleParseError, ParsedDNA

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"

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

def log_observability(step: str, outcome: Outcome, correlation_id: str, dna: Optional[str] = None, error: Optional[str] = None, latency_ms: Optional[float] = None):
    """
    Standardized logging for DNA processing telemetry.
    Grep Recipe: grep "| TELEMETRY |" <log_file> | jq '.data'
    """
    payload = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome.value,
        "actor_id": "jules"
    }
    if dna:
        payload["dna"] = dna
    if error:
        payload["error"] = error
    if latency_ms is not None:
        payload["latency_ms"] = round(latency_ms, 2)

    print(f"| TELEMETRY | {json.dumps({'data': payload})}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_list = []
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
            return {"system_heat": 0.0}
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main():
    start_time = time.time()
    correlation_id = str(uuid.uuid4())
    log_observability("Batch Start", Outcome.START, correlation_id)

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    data_folder = os.path.join(project_root, 'data')
    ledger_path = os.path.join(data_folder, 'processed_ledger.json')
    state_path = os.path.join(data_folder, 'system_state.json')

    ensure_folder(output_folder)

    # Passive thermal dissipation
    state = load_system_state(state_path)
    state["system_heat"] = max(0.0, round(state["system_heat"] - 0.5, 2))

    if state["system_heat"] > 10.0:
        log_observability("Thermal Check", Outcome.ERROR, correlation_id, error="ThermalOverloadError")
        save_system_state(state_path, state)
        raise ThermalOverloadError("System heat exceeds threshold of 10.0")

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability("Input Check", Outcome.END, correlation_id, error="Input file not found", latency_ms=(time.time()-start_time)*1000)
        save_system_state(state_path, state)
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability("Rule Load", Outcome.ERROR, correlation_id, error=str(e))
        save_system_state(state_path, state)
        raise RuleLoadError(f"Could not load rules") from e

    dna_list = read_input_file(input_file)
    if not dna_list:
        log_observability("Batch End", Outcome.END, correlation_id, latency_ms=(time.time()-start_time)*1000)
        save_system_state(state_path, state)
        return

    ledger = load_ledger(ledger_path)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
        except Exception:
            pass

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

    new_work_done = False
    heat_to_add = 0.0
    for dna_str in dna_list:
        if dna_str in ledger:
            log_observability("Idempotency", Outcome.SKIPPED, correlation_id, dna=dna_str)
            continue

        new_work_done = True
        try:
            result = calculator.parse(dna_str)
            # Fatigue system: VOL increases heat
            if result.rule == "Volume":
                amp = result.values.get('amp', 0)
                heat_to_add += (amp / 100.0)

            # Apply thermal penalties to Clarity
            if result.rule == "Clarity":
                system_heat = state["system_heat"]
                if 'noise_floor' in result.values:
                    # noise_floor is {'sign': 'N', 'value': 90}
                    # Penality decreases integer value (effectively raising noise floor)
                    current_val = result.values['noise_floor'].get('value', 0)
                    result.values['noise_floor']['value'] = max(0, current_val - int(system_heat))
                if 'thd' in result.values:
                    current_thd = result.values['thd']
                    result.values['thd'] = min(1000, current_thd + int(system_heat) * 10)

            entry = {
                'dna': dna_str,
                'rule': result.rule,
                'parsed': result.values
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result.rule, result.values)
            flat['dna'] = dna_str
            flat['rule'] = result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            ledger[dna_str] = {
                'terminal_outcome': Outcome.SUCCESS.value,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            log_observability("Processing", Outcome.SUCCESS, correlation_id, dna=dna_str)

        except RuleParseError as e:
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            ledger[dna_str] = {
                'terminal_outcome': Outcome.ERROR.value,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            log_observability("Processing", Outcome.ERROR, correlation_id, dna=dna_str, error=str(e))

    state["system_heat"] = round(state["system_heat"] + heat_to_add, 2)

    if new_work_done:
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
                        writer.writerow({k: row.get(k, '') for k in fieldnames})
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

    save_system_state(state_path, state)
    log_observability("Batch End", Outcome.END, correlation_id, latency_ms=(time.time()-start_time)*1000)

if __name__ == '__main__':
    main()
