#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

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
    """Raised when the system is too hot to process more sequences."""
    pass

# Thermal Fatigue Constants
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0  # units per second

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms=0, idempotency_key=None, extra=None):
    """Emits a structured JSON log with the JSON_LOG: prefix."""
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key
    }
    if extra:
        log_data.update(extra)
    print(f"JSON_LOG:{json.dumps(log_data)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_sequence_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_sequence_list.append(s)
    return dna_sequence_list

def flatten_parsed(rule_name, values_dict, parent_key=''):
    items = {}
    for k, v in values_dict.items():
        new_key = f"{parent_key}.{k}" if parent_key else f"{rule_name}.{k}"
        if isinstance(v, dict):
            items.update(flatten_parsed(rule_name, v, new_key))
        else:
            items[new_key] = v
    return items

def load_ledger_state(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Compatibility: if it's an old flat ledger, wrap it
                if not isinstance(data, dict) or "ledger" not in data:
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                        "ledger": data if isinstance(data, dict) else {}
                    }
                return data
        except Exception:
            pass
    return {
        "system_heat": 0.0,
        "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "ledger": {}
    }

def main(correlation_id="batch-default", actor_id="system"):
    chain_name = "DNA Batch Processing"
    start_time = time.time()

    log_structured(correlation_id, actor_id, chain_name, "start", "initiated")

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, actor_id, chain_name, "read_input", "error", extra={"reason": "file_not_found"})
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, actor_id, chain_name, "load_rules", "error", extra={"reason": str(e)})
        raise RuleLoadError(f"Could not load rules") from e

    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, actor_id, chain_name, "read_input", "error", extra={"reason": str(e)})
        raise DNAProcessingError(f"Failed to read input file") from e

    state = load_ledger_state(ledger_path)
    ledger = state["ledger"]
    system_heat = state.get("system_heat", 0.0)

    # Dissipate heat since last run
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        last_time_str = state.get("last_processed_timestamp")
        last_time = datetime.datetime.fromisoformat(last_time_str.replace('Z', '+00:00'))
        elapsed = (now - last_time).total_seconds()
        system_heat = max(0.0, system_heat - (elapsed * COOLING_RATE))
    except (ValueError, TypeError):
        pass

    if not dna_sequence_list:
        log_structured(correlation_id, actor_id, chain_name, "process", "skipped", extra={"reason": "empty_input"})
        # Update heat dissipation record
        state["system_heat"] = system_heat
        state["last_processed_timestamp"] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        save_ledger_atomic(ledger_path, state)
        return

    # Load existing outputs for cumulative update
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list): parsed_json = []
        except Exception: pass

    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as cf:
                reader = csv.DictReader(cf)
                if reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    csv_rows = list(reader)
        except Exception: pass

    new_processed_count = 0
    error_occurred = None

    try:
        for dna_sequence in dna_sequence_list:
            idempotency_key = dna_sequence

            if idempotency_key in ledger:
                prev_outcome = ledger[idempotency_key].get('terminal_outcome')
                if prev_outcome in [DNAStatus.SUCCESS.value, DNAStatus.ERROR.value, DNAStatus.SKIPPED.value]:
                    log_structured(correlation_id, actor_id, chain_name, "process_item", "skipped",
                                   idempotency_key=idempotency_key, extra={"reason": "idempotency_hit", "previous_outcome": prev_outcome})
                    continue

            # Check Thermal Lockout
            if system_heat + HEAT_PER_SEQ > MAX_HEAT:
                log_structured(correlation_id, actor_id, chain_name, "process_item", "refused",
                               idempotency_key=idempotency_key, extra={"reason": "thermal_lockout", "current_heat": system_heat})
                print("Heat Accumulation: Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines.")
                # Mark as refused in ledger so we know it was attempted but blocked
                ledger[idempotency_key] = {
                    "terminal_outcome": DNAStatus.REFUSED.value,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                }
                raise ThermalOverloadError("Thermal Overload")

            step_start = time.time()
            try:
                result = calculator.parse(dna_sequence)
                entry = {'dna_sequence': dna_sequence, 'rule': result['rule'], 'parsed': result['values']}
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna_sequence'] = dna_sequence
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                outcome = DNAStatus.SUCCESS.value
                system_heat += HEAT_PER_SEQ
            except RuleParseError as e:
                parsed_json.append({'dna_sequence': dna_sequence, 'error': str(e)})
                flat = {'dna_sequence': dna_sequence, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR.value

            latency = int((time.time() - step_start) * 1000)
            log_structured(correlation_id, actor_id, chain_name, "process_item", outcome,
                           latency_ms=latency, idempotency_key=idempotency_key)

            ledger[idempotency_key] = {
                "terminal_outcome": outcome,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            new_processed_count += 1

    except ThermalOverloadError as e:
        error_occurred = e
    except Exception as e:
        error_occurred = e
        log_structured(correlation_id, actor_id, chain_name, "process", "error", extra={"reason": str(e)})

    # Final State Update
    state["system_heat"] = system_heat
    state["last_processed_timestamp"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    state["ledger"] = ledger

    # Persist results atomically
    try:
        commit_results_atomic(json_output_path, csv_output_path, ledger_path,
                              parsed_json, csv_rows, all_flattened_keys, state)
    except Exception as e:
        if not error_occurred:
            raise PersistenceError("Atomic commit failed") from e
        else:
            print(f"[CRITICAL] Persistence failed after loop error: {e}")

    total_latency = int((time.time() - start_time) * 1000)
    final_outcome = "success" if not error_occurred else "partial_or_error"
    log_structured(correlation_id, actor_id, chain_name, "end", final_outcome, latency_ms=total_latency)

    if error_occurred:
        raise error_occurred

def save_ledger_atomic(ledger_path, state):
    dir_name = os.path.dirname(ledger_path)
    with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
        json.dump(state, tf, indent=2)
        temp_name = tf.name
    os.replace(temp_name, ledger_path)

def commit_results_atomic(json_path, csv_path, ledger_path, parsed_json, csv_rows, all_keys, state):
    dir_name = os.path.dirname(json_path)
    with tempfile.TemporaryDirectory(dir=dir_name) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'out.json')
        tmp_csv = os.path.join(tmp_dir, 'out.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

        with open(tmp_json, 'w', encoding='utf-8') as f:
            json.dump(parsed_json, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        fieldnames = sorted(all_keys)
        with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in csv_rows:
                writer.writerow({k: row.get(k, '') for k in fieldnames})
            f.flush()
            os.fsync(f.fileno())

        with open(tmp_ledger, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_json, json_path)
        os.replace(tmp_csv, csv_path)
        os.replace(tmp_ledger, ledger_path)

if __name__ == '__main__':
    main()
