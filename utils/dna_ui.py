#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import getpass
from enum import Enum
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    NO_NEW_DNA = "NO_NEW_DNA"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"

def log_observability(chain_name, step, outcome, correlation_id=None, latency_ms=0, idempotency_key=None, error_message=None):
    """
    Standardized structured logging for SonicDNA.
    """
    ts = datetime.now(timezone.utc).isoformat()
    cid = correlation_id or str(uuid.uuid4())
    actor = getpass.getuser()
    msg = f" | {error_message}" if error_message else ""

    log_line = (f"{ts} | {cid} | {chain_name} | {step} | {outcome.value if isinstance(outcome, Outcome) else outcome} | "
                f"{latency_ms}ms | {actor} | {idempotency_key or 'N/A'}{msg}")

    print(log_line)
    # In a real app, we might write to a file or a logging service here.
    return cid

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

import tempfile
import shutil

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
    """Raised when system heat prevents processing specific DNA."""
    pass

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

def main(data_dir=None):
    start_time = time.time()
    cid = log_observability("dna_batch_chain", "START", Outcome.START)

    # Determine file paths
    project_root = data_dir or os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')

    ensure_folder(output_folder)
    ensure_folder(os.path.join(project_root, 'data'))

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability("dna_batch_chain", "END", Outcome.END, correlation_id=cid, error_message=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    rules_path = os.path.join(project_root, 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_path)
    except Exception as e:
        log_observability("dna_batch_chain", "END", Outcome.ERROR, correlation_id=cid, error_message=str(e))
        raise RuleLoadError(f"Could not load rules from {rules_path}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("dna_batch_chain", "END", Outcome.ERROR, correlation_id=cid, error_message=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability("dna_batch_chain", "END", Outcome.END, correlation_id=cid)
        return

    ledger = load_ledger(ledger_path)
    state = load_system_state(state_path)
    system_heat = state.get("system_heat", 0.0)

    # Natural cooling at batch start
    system_heat = max(0.0, system_heat - 1.0)

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
    batch_errors = 0
    batch_successes = 0

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability("dna_batch_chain", "PROCESS_ITEM", Outcome.SKIPPED, correlation_id=cid, idempotency_key=idempotency_key)
            continue

        log_observability("dna_batch_chain", "PROCESS_ITEM", Outcome.PROCESSING, correlation_id=cid, idempotency_key=idempotency_key)

        error_msg = None
        try:
            # Fatigue Logic
            consequence = None
            if dna_str.startswith("CLA") and system_heat > 2.0:
                if system_heat > 10.0:
                    raise ThermalOverloadError(f"Thermal overload ({system_heat:.1f}). REFUSAL_REASON: System too hot for clarity parsing. NEXT_ACTION_HINT: Process lower-energy DNA or wait for cooling.")

                # Penalty: increase noise floor by system_heat
                consequence = f"CONSEQUENCE_APPLIED: Thermal noise penalty of {int(system_heat)} applied to noise_floor. NEXT_ACTION_HINT: System is warming up."

            result = calculator.parse(dna_str)

            # Apply Clarity penalty if needed
            if consequence and result['rule'] == 'Clarity':
                # noise_floor is signed N + 3 digits
                # result['values']['noise_floor'] is {'sign': 'N', 'value': 90}
                original_val = result['values']['noise_floor']['value']
                # Penalty: noise floor gets higher (less negative)
                new_val = max(0, original_val - int(system_heat))
                result['values']['noise_floor']['value'] = new_val
                result['values']['thermal_penalty'] = int(system_heat)

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values'],
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            if consequence:
                entry['consequence'] = consequence

            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            if consequence:
                flat['consequence'] = consequence
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            # Heat gain from Volume
            if result['rule'] == 'Volume':
                amp = result['values'].get('amp', 0)
                system_heat += amp / 100.0

            outcome = Outcome.SUCCESS
            batch_successes += 1

        except (RuleParseError, ThermalOverloadError) as e:
            error_msg = str(e)
            parsed_json.append({
                'dna': dna_str,
                'error': error_msg,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            flat = {'dna': dna_str, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR
            batch_errors += 1

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        log_observability("dna_batch_chain", "PROCESS_ITEM", outcome, correlation_id=cid, idempotency_key=idempotency_key, error_message=error_msg)
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # Stage files in temp, then rename.
    # We update system_state even if new_processed_count == 0 to persist natural cooling.

    with tempfile.TemporaryDirectory(dir=os.path.join(project_root, 'data')) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
        tmp_state = os.path.join(tmp_dir, 'state.json')

        try:
            # 1) JSON
            with open(tmp_json, 'w', encoding='utf-8') as jf:
                json.dump(parsed_json, jf, indent=2)
                jf.flush()
                os.fsync(jf.fileno())

            # 2) CSV
            fieldnames = sorted(all_flattened_keys)
            with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                writer = csv.DictWriter(cf, fieldnames=fieldnames)
                writer.writeheader()
                for row in csv_rows:
                    out = {k: row.get(k, '') for k in fieldnames}
                    writer.writerow(out)
                cf.flush()
                os.fsync(cf.fileno())

            # 3) Ledger
            with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                json.dump(ledger, lf, indent=2)
                lf.flush()
                os.fsync(lf.fileno())

            # 4) State
            with open(tmp_state, 'w', encoding='utf-8') as sf:
                json.dump({"system_heat": system_heat}, sf, indent=2)
                sf.flush()
                os.fsync(sf.fileno())

            # Atomic rename (commit)
            if new_processed_count > 0:
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            # Always update state for cooling
            os.replace(tmp_state, state_path)

        except Exception as e:
            log_observability("dna_batch_chain", "COMMIT", Outcome.ERROR, correlation_id=cid, error_message=str(e))
            raise PersistenceError("Failed to write output files atomically") from e

    final_outcome = Outcome.SUCCESS
    if batch_errors > 0:
        final_outcome = Outcome.PARTIAL_SUCCESS if batch_successes > 0 else Outcome.ERROR
    if new_processed_count == 0:
        final_outcome = Outcome.NO_NEW_DNA

    latency = int((time.time() - start_time) * 1000)
    log_observability("dna_batch_chain", "END", final_outcome, correlation_id=cid, latency_ms=latency)

    if dna_list:
        print(f"[OK] Processed {new_processed_count} DNA strings. Heat: {system_heat:.2f}")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
