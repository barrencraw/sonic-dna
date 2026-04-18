#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import getpass
import uuid
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
    """Raised when system heat is too high for certain rules."""
    pass

def log_observability(step, outcome, latency_ms=0, correlation_id=None, idempotency_key=None, error_message=None):
    """
    Standardized structured logging for observability.
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "latency_ms": latency_ms,
        "actor_id": getpass.getuser(),
        "idempotency_key": idempotency_key
    }
    if error_message:
        log_entry["error_message"] = error_message

    print(f"[OBSERVABILITY] {json.dumps(log_entry)}")

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
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main():
    start_time = time.time()
    correlation_id = str(uuid.uuid4())
    log_observability("batch_init", Outcome.START, correlation_id=correlation_id)

    # Determine file paths
    project_root = os.getcwd()
    data_folder = os.path.join(project_root, 'data')
    raw_folder = os.path.join(data_folder, 'raw')
    output_folder = os.path.join(data_folder, 'output')
    ledger_path = os.path.join(data_folder, 'processed_ledger.json')
    state_path = os.path.join(data_folder, 'system_state.json')

    ensure_folder(data_folder)
    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_observability("input_check", Outcome.ERROR, correlation_id=correlation_id, error_message="Input file not found")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability("calculator_init", Outcome.ERROR, correlation_id=correlation_id, error_message=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("read_input", Outcome.ERROR, correlation_id=correlation_id, error_message=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    # Load system state early for cooling
    state = load_system_state(state_path)
    if dna_list:
        # Natural cooling
        state["system_heat"] = max(0.0, state["system_heat"] - 1.0)
        print(f"[System] Natural cooling applied. Current heat: {state['system_heat']:.2f}")

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        # Save cooling even if no DNA
        save_system_state(state_path, state)
        log_observability("read_input", Outcome.END, correlation_id=correlation_id)
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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            log_observability("dna_process", Outcome.SKIPPED, correlation_id=correlation_id, idempotency_key=idempotency_key)
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
        log_observability("dna_process", Outcome.PROCESSING, correlation_id=correlation_id, idempotency_key=idempotency_key)

        error_msg = None
        consequence_applied = None
        refusal_reason = None
        next_action_hint = None

        try:
            result = calculator.parse(dna_str)

            # Fatigue Logic: Heat Gain for Volume
            if result['rule'] == 'Volume':
                amp = result['values'].get('amp', 0)
                heat_gain = amp / 100.0
                state["system_heat"] += heat_gain
                print(f"[System] Volume processed. Heat gain: +{heat_gain:.2f}. Total heat: {state['system_heat']:.2f}")

            # Fatigue Logic: Penalty/Refusal for Clarity
            if result['rule'] == 'Clarity':
                if state["system_heat"] > 10.0:
                    refusal_reason = f"Thermal overload: system heat ({state['system_heat']:.2f}) exceeds threshold (10.00)."
                    next_action_hint = "Cease high-amplitude operations. Allow system to cool."
                    raise ThermalOverloadError(refusal_reason)

                if state["system_heat"] > 0.0:
                    penalty = int(state["system_heat"])
                    # noise_floor is a dict with 'sign' and 'value'. Value is 0-120 (dBFS).
                    # Raising the noise floor means decreasing the negative value (e.g. -90 to -85).
                    if 'noise_floor' in result['values']:
                        old_val = result['values']['noise_floor']['value']
                        new_val = max(0, old_val - penalty)
                        result['values']['noise_floor']['value'] = new_val
                        consequence_applied = f"Thermal noise penalty: noise floor raised by {penalty}dB due to heat."
                        print(f"[System] Clarity penalized. {consequence_applied}")

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            if consequence_applied:
                entry['CONSEQUENCE_APPLIED'] = consequence_applied

            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            if consequence_applied:
                flat['CONSEQUENCE_APPLIED'] = consequence_applied

            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS

        except (RuleParseError, ThermalOverloadError) as e:
            # On error, record as error entry
            error_entry = {
                'dna': dna_str,
                'error': str(e)
            }
            if refusal_reason:
                error_entry['REFUSAL_REASON'] = refusal_reason
            if next_action_hint:
                error_entry['NEXT_ACTION_HINT'] = next_action_hint

            parsed_json.append(error_entry)

            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e)}
            if refusal_reason:
                flat['REFUSAL_REASON'] = refusal_reason
            if next_action_hint:
                flat['NEXT_ACTION_HINT'] = next_action_hint

            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR
            error_msg = str(e)

        except Exception as e:
            outcome = Outcome.ERROR
            error_msg = str(e)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome.value}")
        log_observability("dna_process", outcome, correlation_id=correlation_id, idempotency_key=idempotency_key, error_message=error_msg)
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # Always save state if we processed something or applied cooling
    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
        tmp_state = os.path.join(tmp_dir, 'system_state.json')

        try:
            # 1) Write system state
            with open(tmp_state, 'w', encoding='utf-8') as sf:
                json.dump(state, sf, indent=2)
                sf.flush()
                os.fsync(sf.fileno())
            os.replace(tmp_state, state_path)

            if new_processed_count > 0:
                # 2) Write JSON output to temp
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 3) Write CSV output to temp
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 4) Write Ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 5) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

        except Exception as e:
            log_observability("atomic_write", Outcome.ERROR, correlation_id=correlation_id, error_message=str(e))
            raise PersistenceError("Failed to write output files atomically") from e

    if new_processed_count > 0:
        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")
    else:
        print("[OK] No new DNA strings to process.")

    latency = int((time.time() - start_time) * 1000)
    log_observability("batch_complete", Outcome.END, latency_ms=latency, correlation_id=correlation_id)

if __name__ == '__main__':
    main()
