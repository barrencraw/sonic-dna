#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import getpass
import tempfile
import shutil
from datetime import datetime, timezone
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    NO_NEW_DNA = "NO_NEW_DNA"

def log_observability(step, outcome, correlation_id, idempotency_key=None, latency_ms=0, error_message=None):
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": str(correlation_id),
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "latency_ms": latency_ms,
        "actor_id": getpass.getuser(),
        "idempotency_key": idempotency_key
    }
    if error_message:
        log_entry["error_message"] = error_message

    print(f"[{log_entry['timestamp']}] chain=dna_batch_chain step={step} outcome={log_entry['outcome']} "
          f"corr={log_entry['correlation_id']} key={idempotency_key} lat={latency_ms}ms" +
          (f" err={error_message}" if error_message else ""))

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
    correlation_id = uuid.uuid4()
    start_time_all = time.time()
    log_observability("init", Outcome.START, correlation_id)

    # Determine file paths
    project_root = data_dir if data_dir else os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability("input_check", Outcome.END, correlation_id, error_message=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        rules_folder = os.path.join(project_root, 'rules')
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        log_observability("rule_load", Outcome.ERROR, correlation_id, error_message=str(e))
        raise RuleLoadError(f"Could not load rules from {rules_folder}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("input_read", Outcome.ERROR, correlation_id, error_message=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability("input_process", Outcome.NO_NEW_DNA, correlation_id)
        log_observability("finalize", Outcome.END, correlation_id)
        return

    ledger = load_ledger(ledger_path)
    system_state = load_system_state(state_path)
    system_heat = system_state.get("system_heat", 0.0)

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
    seen_in_batch = set()

    for dna_str in dna_list:
        if dna_str in seen_in_batch:
            continue
        seen_in_batch.add(dna_str)

        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability("dedupe", Outcome.SKIPPED, correlation_id, idempotency_key=idempotency_key)
            continue

        loop_start = time.time()
        log_observability("parse_start", Outcome.PROCESSING, correlation_id, idempotency_key=idempotency_key)

        outcome = Outcome.SUCCESS
        error_msg = None
        flattened_vals = {}

        try:
            # FATIGUE SYSTEM: Refusal logic
            if dna_str.startswith("CLA") and system_heat > 10.0:
                raise ThermalOverloadError(f"Thermal overload (heat={system_heat:.2f}). Refusing Clarity parse.")

            result = calculator.parse(dna_str)

            # FATIGUE SYSTEM: Penalty logic
            if result['rule'] == 'Clarity' and system_heat > 0:
                original_nf = result['values'].get('noise_floor', {}).get('value', 0)
                penalty = int(system_heat)
                new_nf = original_nf - penalty # Raising noise floor (less negative)
                result['values']['noise_floor']['value'] = max(0, new_nf)
                print(f"[Fatigue] CONSEQUENCE_APPLIED: Noise floor raised by {penalty}dB due to heat.")

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flattened_vals = flatten_parsed(result['rule'], result['values'])
            flattened_vals['dna'] = dna_str
            flattened_vals['rule'] = result['rule']
            csv_rows.append(flattened_vals)
            all_flattened_keys.update(flattened_vals.keys())

            # FATIGUE SYSTEM: Heat gain
            if result['rule'] == 'Volume':
                amp = result['values'].get('amp', 0)
                heat_gain = amp / 100.0
                system_heat += heat_gain
                print(f"[Fatigue] System heat increased by {heat_gain:.2f} to {system_heat:.2f}")

        except (RuleParseError, ThermalOverloadError) as e:
            outcome = Outcome.ERROR
            error_msg = str(e)
            parsed_json.append({
                'dna': dna_str,
                'error': error_msg
            })
            flattened_vals = {'dna': dna_str, 'error': error_msg}
            csv_rows.append(flattened_vals)
            all_flattened_keys.update(flattened_vals.keys())

        latency = int((time.time() - loop_start) * 1000)
        log_observability("parse_end", outcome, correlation_id, idempotency_key=idempotency_key, latency_ms=latency, error_message=error_msg)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        new_processed_count += 1

    if new_processed_count > 0:
        system_state["system_heat"] = system_heat
        # ATOMIC WRITE PATTERN
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_state = os.path.join(tmp_dir, 'state.json')

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

                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump(system_state, sf, indent=2)
                    sf.flush()
                    os.fsync(sf.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, state_path)
            except Exception as e:
                log_observability("persistence", Outcome.ERROR, correlation_id, error_message=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    total_latency = int((time.time() - start_time_all) * 1000)
    log_observability("finalize", Outcome.END, correlation_id, latency_ms=total_latency)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
