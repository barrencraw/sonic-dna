#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
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
    """Raised when the system is too hot to process DNA."""
    pass

def log_observability(step, outcome, latency_ms=0, correlation_id=None, idempotency_key=None):
    """Standardized structured log fields for DNA processing telemetry."""
    project_root = os.getcwd()
    # Find data folder relative to project root
    if os.path.basename(project_root) == 'data' or 'data' in os.listdir(project_root):
        data_dir = os.path.join(project_root, 'data') if 'data' in os.listdir(project_root) else project_root
    else:
        # Fallback to absolute project root if known, or just use current dir
        data_dir = os.path.join(project_root, 'data')

    log_file = os.path.join(data_dir, 'sonicdna.log')
    ensure_folder(os.path.dirname(log_file))

    entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id or "N/A",
        "chain_name": "DNA_BATCH_PARSER",
        "step": step,
        "outcome": outcome.upper(),
        "latency_ms": latency_ms,
        "actor_id": "sonicdna_batch_processor",
        "idempotency_key": idempotency_key or "N/A"
    }

    log_line = f"{entry['timestamp']} | TELEMETRY | {json.dumps(entry)}\n"
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_line)

def load_system_state(state_path):
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {"system_heat": 0.0}
        except Exception:
            return {"system_heat": 0.0}
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

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
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def main():
    start_time = time.time()
    correlation_id = str(uuid.uuid4())

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability("START", "ERROR", correlation_id=correlation_id)
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("START", "ERROR", correlation_id=correlation_id)
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    log_observability("START", "SUCCESS", correlation_id=correlation_id)

    ledger = load_ledger(ledger_path)
    system_state = load_system_state(state_path)

    # Passive dissipation
    system_state["system_heat"] = max(0.0, round(system_state["system_heat"] - 0.5, 2))

    # Thermal Overload Check
    if system_state["system_heat"] > 10.0:
        log_observability("BATCH", "REFUSAL", correlation_id=correlation_id)
        raise ThermalOverloadError(f"System heat ({system_state['system_heat']}) exceeds threshold (10.0).")

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
    new_ledger_entries = {}

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger or idempotency_key in new_ledger_entries:
            log_observability("IDEMPOTENCY", "SKIPPED", correlation_id=correlation_id, idempotency_key=idempotency_key)
            continue

        try:
            # Systemic Feedback Logic
            current_heat = system_state["system_heat"]

            # Penalize Clarity (CLA)
            if dna_str.startswith("CLA"):
                # We need to parse first to get subvars, but penalties apply to the result.
                # Actually, according to memory, the penalty is applied to the DNA values.
                pass

            result = calculator.parse(dna_str)
            rule_name = result['rule']
            values = result['values']

            # Heat Gain from Volume (VOL)
            if rule_name == "Volume":
                amp = values.get("amp", 0)
                system_state["system_heat"] = round(system_state["system_heat"] + (amp / 100.0), 2)

            # Fatigue Penalty for Clarity (CLA)
            if rule_name == "Clarity":
                values["noise_floor"] = values.get("noise_floor", 0) + int(current_heat)
                values["thd"] = min(1000, values.get("thd", 0) + int(current_heat) * 10)

            entry = {
                'dna': dna_str,
                'rule': rule_name,
                'parsed': values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(rule_name, values)
            flat['dna'] = dna_str
            flat['rule'] = rule_name
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except RuleParseError as e:
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        new_ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_observability("IDEMPOTENCY", outcome, correlation_id=correlation_id, idempotency_key=idempotency_key)
        new_processed_count += 1

    # Merge new ledger entries
    ledger.update(new_ledger_entries)

    # ATOMIC COMMIT
    # We commit even if new_processed_count == 0 to save passive dissipation
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
                json.dump(system_state, sf, indent=2)
                sf.flush(); os.fsync(sf.fileno())

            # Atomic rename
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)
            os.replace(tmp_state, state_path)

        except Exception as e:
            log_observability("END", "ERROR", latency_ms=int((time.time()-start_time)*1000), correlation_id=correlation_id)
            raise PersistenceError("Failed to write output files atomically") from e

    latency = int((time.time() - start_time) * 1000)
    log_observability("END", "SUCCESS", latency_ms=latency, correlation_id=correlation_id)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Heat: {system_state['system_heat']}")

if __name__ == '__main__':
    main()
