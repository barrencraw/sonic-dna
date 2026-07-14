#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
import uuid
from dataclasses import dataclass
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Constants ---
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0  # units per second

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

@dataclass
class BatchResult:
    total_sequences: int
    newly_processed: int
    success_count: int
    error_count: int
    skipped_count: int

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
    """Raised when hardware heat exceeds safety limits."""
    pass

def log_structured(correlation_id, step, outcome, latency_ms=0, actor_id="system", chain_name="dna_processing", idempotency_key=None, outcome_detail=None):
    """Emits a structured JSON log with the JSON_LOG: prefix."""
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")

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
                # Backward compatibility: if ledger is a list or missing top-level structure
                if isinstance(data, dict) and 'ledger' in data:
                    return data
                return {'ledger': data, 'system_heat': 0.0, 'last_update': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        except Exception:
            pass
    return {'ledger': {}, 'system_heat': 0.0, 'last_update': datetime.datetime.now(datetime.timezone.utc).isoformat()}

def save_ledger(ledger_path, state):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    start_time = time.time()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, "load_rules", "error", outcome_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, "read_input", "error", outcome_detail=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    state = load_ledger(ledger_path)
    ledger = state['ledger']
    current_heat = float(state.get('system_heat', 0.0))
    last_update_str = state.get('last_update')

    # 1. Heat Dissipation
    if last_update_str:
        try:
            last_time = datetime.datetime.fromisoformat(last_update_str).timestamp()
            elapsed = time.time() - last_time
            if elapsed > 0:
                dissipation = elapsed * COOLING_RATE
                current_heat = max(0.0, current_heat - dissipation)
        except (ValueError, TypeError):
            pass

    # 2. Load existing outputs
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
    skipped_count = 0
    error_to_raise = None

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str

            # Idempotency check
            if idempotency_key in ledger:
                skipped_count += 1
                continue

            # Thermal Check
            if current_heat >= MAX_HEAT:
                log_structured(correlation_id, "process_dna", "refused",
                               idempotency_key=idempotency_key,
                               outcome_detail="Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines.")
                error_to_raise = ThermalOverloadError("Thermal Lockout")
                break

            # Process DNA
            item_start = time.time()
            try:
                result = calculator.parse(dna_str)
                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                outcome = DNAStatus.SUCCESS.value
                success_count += 1
            except RuleParseError as e:
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e)
                })
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                outcome = DNAStatus.ERROR.value
                error_count += 1

            # Accumulate Heat
            current_heat += HEAT_PER_SEQ
            log_structured(correlation_id, "process_dna", outcome,
                           latency_ms=int((time.time() - item_start) * 1000),
                           idempotency_key=idempotency_key,
                           outcome_detail="Heat Accumulation")

            # Update ledger for each item (Indentation fix from memory)
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            new_processed_count += 1

    except Exception as e:
        if not error_to_raise:
            error_to_raise = e

    # Update state
    state['system_heat'] = current_heat
    state['last_update'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state['ledger'] = ledger

    # Commit results
    error_occurred = (error_to_raise is not None)
    try:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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
                json.dump(state, lf, indent=2)
                lf.flush()
                os.fsync(lf.fileno())

            # Atomic Commit
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)

    except Exception as e:
        if not error_occurred:
            raise PersistenceError("Failed to write output files atomically") from e

    if error_to_raise:
        raise error_to_raise

    return BatchResult(
        total_sequences=len(dna_list),
        newly_processed=new_processed_count,
        success_count=success_count,
        error_count=error_count,
        skipped_count=skipped_count
    )

if __name__ == '__main__':
    # Renaming main to run_batch for clarity, but keeping main entry point
    run_batch()
