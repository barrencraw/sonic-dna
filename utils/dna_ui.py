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

# --- Enums & Data Classes ---

class DNAStatus(Enum):
    SUCCESS = 'success'
    PARSE_ERROR = 'error'
    SKIPPED = 'skipped'
    PROCESSING = 'processing'

# --- Exceptions ---

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class DataIntegrityError(DNAProcessingError):
    """Raised when corrupted outputs are detected."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system heat limits are exceeded."""
    pass

# --- Helpers ---

def log_structured(correlation_id, chain_name, step, outcome_val, actor_id="system", **kwargs):
    """
    Standardized JSON logging for SonicDNA.
    """
    entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome_val,
        "actor_id": actor_id
    }
    entry.update(kwargs)
    print(f"JSON_LOG: {json.dumps(entry)}")

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

def calculate_heat_delta(result):
    """
    Calculate heat gain for a processed DNA sequence.
    """
    base_heat = 0.1
    if result['rule'] == 'Volume':
        # Specific heat gain for 'Volume' DNA sequences (prefix 'VOL')
        # is 0.1 + (amp / 500.0)
        amp = result['values'].get('level', 0)
        return base_heat + (amp / 500.0)
    return base_heat

def apply_thermal_noise(data, factor=0.9):
    """
    Recursively scales numeric leaf values (excluding booleans) by factor.
    """
    if isinstance(data, dict):
        return {k: apply_thermal_noise(v, factor) for k, v in data.items()}
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        return data * factor
    return data

def main(correlation_id=None, base_dir=None):
    # Determine file paths
    if base_dir is None:
        base_dir = os.getcwd()

    data_folder = os.path.join(base_dir, 'data')
    raw_folder = os.path.join(data_folder, 'raw')
    output_folder = os.path.join(data_folder, 'output')
    ledger_path = os.path.join(data_folder, 'processed_ledger.json')
    system_state_path = os.path.join(data_folder, 'system_state.json')
    ensure_folder(output_folder)

    # Correlation ID for the batch
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    chain_name = "DNA_BATCH_PARSING"

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, chain_name, "start", "error", error=f"Input file not found: {input_file}")
        return

    log_structured(correlation_id, chain_name, "start", "processing", input_file=input_file)

    # Load system heat
    system_heat = 0.0
    if os.path.exists(system_state_path):
        try:
            with open(system_state_path, 'r') as f:
                state = json.load(f)
                system_heat = state.get('system_heat', 0.0)
        except Exception:
            pass

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(base_dir, 'rules'))
    except Exception as e:
        log_structured(correlation_id, chain_name, "rule_load", "error", error=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(base_dir, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, chain_name, "read_input", "error", error=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured(correlation_id, chain_name, "read_input", "skipped", reason="empty_input")
        return

    ledger = load_ledger(ledger_path)

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
    fatal_error = None
    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                log_structured(correlation_id, chain_name, "dedupe", "skipped", idempotency_key=idempotency_key, dedupe_hit=True, terminal_outcome=ledger[idempotency_key]['terminal_outcome'])
                continue

            outcome = DNAStatus.PROCESSING.value
            try:
                result = calculator.parse(dna_str)

                # Thermal Fatigue logic
                heat_gain = calculate_heat_delta(result)
                if system_heat + heat_gain > 10.0:
                    system_heat += heat_gain # Increment before raising as per memory
                    log_structured(correlation_id, chain_name, "thermal_refusal", "fatal", system_heat=system_heat, limit=10.0)
                    print("[FATAL] Thermal Overload. Core temperature exceeding safety limits.")
                    raise ThermalOverloadError("Thermal Overload")

                system_heat += heat_gain

                values = result['values']
                if system_heat > 7.0:
                    print("[WARN] Thermal Noise detected. Fidelity degradation active.")
                    values = apply_thermal_noise(values, factor=0.9)

                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': values,
                    'system_heat': round(system_heat, 2)
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], values)
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                flat['system_heat'] = round(system_heat, 2)
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.SUCCESS.value

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e),
                    'system_heat': round(system_heat, 2)
                })
                # Also put a row in CSV listing error
                flat = {'dna': dna_str, 'error': str(e), 'system_heat': round(system_heat, 2)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.PARSE_ERROR.value

            # Update ledger for this key
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            log_structured(correlation_id, chain_name, "process_item", outcome, idempotency_key=idempotency_key, dedupe_hit=False, system_heat=round(system_heat, 2))
            new_processed_count += 1
    except ThermalOverloadError as e:
        fatal_error = e

    # Save outputs even if we had a thermal overload (atomic commit of what was done)
    if new_processed_count > 0 or system_heat > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)

        with tempfile.TemporaryDirectory(dir=os.path.dirname(ledger_path)) as tmp_dir:
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

                # 3) Write Ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Write System State to temp
                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump({'system_heat': system_heat}, sf, indent=2)
                    sf.flush()
                    os.fsync(sf.fileno())

                # 5) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, system_state_path)

            except Exception as e:
                log_structured(correlation_id, chain_name, "commit", "error", error=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    log_structured(correlation_id, chain_name, "complete", "success" if not fatal_error else "fatal", new_items=new_processed_count, total_ledger=len(ledger), final_heat=round(system_heat, 2))

    if fatal_error:
        raise fatal_error

if __name__ == '__main__':
    main()
