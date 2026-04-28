#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
from enum import Enum
from dataclasses import asdict
from utils.dna_calculator import DNACalculator, RuleParseError, ParsedDNA

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    NO_NEW_DNA = "NO_NEW_DNA"

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
    """Raised when system heat is too high for certain operations."""
    pass

def log_observability(step, outcome, correlation_id=None, extra=None, actor_id="system"):
    payload = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id or "N/A",
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else str(outcome),
        "actor_id": actor_id
    }
    if extra:
        payload.update(extra)
    print(f"| TELEMETRY | {json.dumps(payload)}")

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

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

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

def main(data_dir=None):
    correlation_id = str(uuid.uuid4())
    log_observability("batch_start", Outcome.START, correlation_id)

    # Determine file paths
    project_root = data_dir if data_dir else os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability("input_check", Outcome.ERROR, correlation_id, {"error": "Input file not found"})
        log_observability("batch_end", Outcome.END, correlation_id)
        return

    # Load system state (Fatigue)
    state = load_system_state(state_path)
    system_heat = state.get("system_heat", 0.0)

    # Natural cooling
    system_heat = max(0.0, system_heat - 1.0)
    state["system_heat"] = system_heat

    # Instantiate calculator
    rules_folder = os.path.join(project_root, 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        log_observability("load_rules", Outcome.ERROR, correlation_id, {"error": str(e)})
        raise RuleLoadError(f"Could not load rules from {rules_folder}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("read_input", Outcome.ERROR, correlation_id, {"error": str(e)})
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        save_system_state(state_path, state)
        log_observability("batch_process", Outcome.NO_NEW_DNA, correlation_id)
        log_observability("batch_end", Outcome.END, correlation_id)
        return

    ledger = load_ledger(ledger_path)

    # Load existing outputs for cumulative update
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list): parsed_json = []
        except Exception:
            parsed_json = []

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
    success_count = 0
    error_count = 0

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability("item_process", Outcome.SKIPPED, correlation_id, {"dna": dna_str, "reason": "idempotency_hit"})
            continue

        log_observability("item_process", Outcome.PROCESSING, correlation_id, {"dna": dna_str})

        try:
            # Fatigue penalty for Clarity DNA
            if dna_str.startswith("CLA"):
                if system_heat > 10.0:
                    raise ThermalOverloadError("System heat exceeds 10.0. Clarity processing refused.")

            result = calculator.parse(dna_str)

            # Apply Fatigue penalties to Clarity values
            if result.rule == "Clarity":
                heat_int = int(system_heat)
                if heat_int > 0:
                    # noise_floor penalty (decreases value, effectively raising noise floor)
                    if 'noise_floor' in result.values:
                        nf = result.values['noise_floor']
                        nf['value'] = max(0, nf['value'] - heat_int)
                    # thd penalty (increases value)
                    if 'thd' in result.values:
                        result.values['thd'] = min(1000, result.values['thd'] + (heat_int * 10))

            # Fatigue accumulation for Volume DNA
            if result.rule == "Volume":
                amp = result.values.get('level', 0)
                system_heat += amp / 100.0

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

            outcome = Outcome.SUCCESS
            success_count += 1

        except Exception as e:
            outcome = Outcome.ERROR
            error_count += 1
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            log_observability("item_process", Outcome.ERROR, correlation_id, {"dna": dna_str, "error": str(e)})

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_observability("item_process", outcome, correlation_id, {"dna": dna_str})
        new_processed_count += 1

    # Atomic Commit Pattern
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

            except Exception as e:
                log_observability("commit", Outcome.ERROR, correlation_id, {"error": str(e)})
                raise PersistenceError("Failed to write output files atomically") from e

    state["system_heat"] = system_heat
    save_system_state(state_path, state)

    final_outcome = Outcome.SUCCESS
    if error_count > 0:
        final_outcome = Outcome.PARTIAL_SUCCESS if success_count > 0 else Outcome.ERROR
    if new_processed_count == 0:
        final_outcome = Outcome.NO_NEW_DNA

    log_observability("batch_process", final_outcome, correlation_id, {
        "new_processed": new_processed_count,
        "success": success_count,
        "error": error_count,
        "system_heat": system_heat
    })
    log_observability("batch_end", Outcome.END, correlation_id)

if __name__ == '__main__':
    main()
