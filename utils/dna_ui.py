#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from utils.dna_calculator import DNACalculator, RuleParseError

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

class ThermalOverloadError(DNAProcessingError):
    """Raised when system_heat exceeds threshold."""
    pass

# --- Telemetry ---
def log_observability(correlation_id, chain_name, step, outcome, latency_ms=0, actor_id="system", idempotency_key=None):
    """
    Standardized telemetry logger.
    Grep Recipe: grep "| TELEMETRY |" <log_file> | jq '.data'
    """
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    payload = {
        "timestamp": timestamp,
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.upper(),
        "latency_ms": latency_ms,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key
    }
    print(f"| TELEMETRY | {json.dumps(payload)}")

# --- System State (Fatigue/Heat) ---
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

# --- Utils ---
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
                return json.load(f)
        except Exception:
            return {}
    return {}

def main(data_dir=None):
    start_time = time.time()
    correlation_id = str(uuid.uuid4())
    log_observability(correlation_id, "dna_batch_chain", "START", "SUCCESS")

    # Determine file paths
    project_root = data_dir if data_dir else os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')

    ensure_folder(output_folder)
    ensure_folder(os.path.join(project_root, 'data'))

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # 1) Load State and Dissipate Heat
    state = load_system_state(state_path)
    system_heat = state.get("system_heat", 0.0)
    system_heat = max(0.0, system_heat - 0.5) # Passive dissipation
    state["system_heat"] = round(system_heat, 2)

    if not os.path.isfile(input_file):
        save_system_state(state_path, state)
        log_observability(correlation_id, "dna_batch_chain", "END", "SUCCESS", latency_ms=int((time.time()-start_time)*1000))
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, "dna_batch_chain", "LOAD_RULES", "ERROR")
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(correlation_id, "dna_batch_chain", "READ_INPUT", "ERROR")
        raise DNAProcessingError(f"Failed to read input file") from e

    if not dna_list:
        save_system_state(state_path, state)
        log_observability(correlation_id, "dna_batch_chain", "END", "SUCCESS", latency_ms=int((time.time()-start_time)*1000))
        return

    # Check Thermal Overload
    if system_heat > 10.0:
        log_observability(correlation_id, "dna_batch_chain", "THERMAL_CHECK", "REFUSAL")
        raise ThermalOverloadError(f"System heat ({system_heat}) exceeds threshold (10.0)")

    ledger = load_ledger(ledger_path)
    new_ledger_entries = {}

    # Load existing outputs
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

    processed_in_batch = set()
    new_processed_count = 0

    for dna_str in dna_list:
        idempotency_key = dna_str

        # Deduplication (In-batch and Ledger)
        if idempotency_key in ledger or idempotency_key in processed_in_batch:
            outcome = ledger.get(idempotency_key, {}).get("terminal_outcome", "SUCCESS").upper()
            log_observability(correlation_id, "dna_batch_chain", "PROCESS_ITEM", outcome, idempotency_key=idempotency_key)
            continue

        processed_in_batch.add(idempotency_key)
        item_start = time.time()

        try:
            result = calculator.parse(dna_str)

            # Fatigue System: Heat gain from Volume (VOL)
            if result['rule'] == 'Volume':
                amp = result['values'].get('level', 0)
                system_heat += (amp / 100.0)

            # Fatigue System: Penalty to Clarity (CLA)
            if result['rule'] == 'Clarity':
                # noise_floor penalty (increases noise floor by decreasing its integer value)
                if 'noise_floor' in result['values']:
                    # In CLA DNA, N090 = -90dB. To raise the floor (make it louder), we decrease the integer.
                    # Wait, the code said "decreases integer value... effectively raising the floor".
                    # If it's 90, and we subtract 10, it becomes 80. N080 is louder than N090. Correct.
                    result['values']['noise_floor']['value'] = max(0, result['values']['noise_floor']['value'] - int(system_heat))
                # thd penalty
                if 'thd' in result['values']:
                    result['values']['thd'] = min(1000, result['values']['thd'] + (int(system_heat) * 10))

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values'],
                'system_heat_at_processing': round(system_heat, 2)
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            flat['system_heat_at_processing'] = round(system_heat, 2)
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = "success"
        except RuleParseError as e:
            outcome = f"error: {str(e)}"
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        new_ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1
        log_observability(correlation_id, "dna_batch_chain", "PROCESS_ITEM", outcome,
                         latency_ms=int((time.time()-item_start)*1000), idempotency_key=idempotency_key)

    # 4) Atomic Commit
    state["system_heat"] = round(system_heat, 2)
    ledger.update(new_ledger_entries)

    # Always attempt to save state (for dissipation) and others if they changed
    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
        tmp_state = os.path.join(tmp_dir, 'state.json')

        try:
            with open(tmp_json, 'w', encoding='utf-8') as jf:
                json.dump(parsed_json, jf, indent=2)
                jf.flush(); os.fsync(jf.fileno())

            fieldnames = sorted(all_flattened_keys)
            with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                writer = csv.DictWriter(cf, fieldnames=fieldnames)
                writer.writeheader()
                for row in csv_rows:
                    writer.writerow({k: row.get(k, '') for k in fieldnames})
                cf.flush(); os.fsync(cf.fileno())

            with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                json.dump(ledger, lf, indent=2)
                lf.flush(); os.fsync(lf.fileno())

            with open(tmp_state, 'w', encoding='utf-8') as sf:
                json.dump(state, sf, indent=2)
                sf.flush(); os.fsync(sf.fileno())

            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)
            os.replace(tmp_state, state_path)
        except Exception as e:
            log_observability(correlation_id, "dna_batch_chain", "COMMIT", "ERROR")
            raise PersistenceError("Failed to write output files atomically") from e

    log_observability(correlation_id, "dna_batch_chain", "END", "SUCCESS", latency_ms=int((time.time()-start_time)*1000))
    print(f"[OK] Processed {new_processed_count} new DNA strings. System Heat: {state['system_heat']}")

if __name__ == '__main__':
    main()
