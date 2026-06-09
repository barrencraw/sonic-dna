#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from utils.dna_calculator import DNACalculator, RuleParseError

# Constants for Thermal Fatigue
MAX_HEAT = 10.0
BASE_HEAT_GAIN = 0.1
VOL_HEAT_PENALTY = 0.2
COOLING_RATE = 0.0083 # ~1 unit every 2 minutes (~0.5 units per minute)

MSG_CONSEQUENCE = "Hardware thermal drift detected. Logic gates may lose coherence."
MSG_REFUSAL = "Hardware safety lockout. Critical heat levels reached."
MSG_HINT = "Wait for natural dissipation. The world does not care for your haste."

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
    """Raised when system heat exceeds MAX_HEAT."""
    pass

def log_structured(correlation_id, step, outcome, dna_sequence=None, latency_ms=None, error=None):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome,
        "actor_id": "system"
    }
    if dna_sequence:
        log_entry["idempotency_key"] = dna_sequence
        log_entry["dna_sequence"] = dna_sequence
    if latency_ms is not None:
        log_entry["latency_ms"] = latency_ms
    if error:
        log_entry["error"] = str(error)

    print(f"JSON_LOG: {json.dumps(log_entry)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_list = []
    if not os.path.exists(input_path):
        return dna_list
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Migration: if it's a flat dict, wrap it
                if "ledger" not in data:
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": time.time(),
                        "ledger": data
                    }
                return data
        except Exception:
            pass
    return {
        "system_heat": 0.0,
        "last_processed_timestamp": time.time(),
        "ledger": {}
    }

def save_ledger(ledger_path, state):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def apply_cooling(state):
    now = time.time()
    last_ts = state.get("last_processed_timestamp", now)
    elapsed = now - last_ts

    cooling = elapsed * COOLING_RATE
    old_heat = state.get("system_heat", 0.0)
    new_heat = max(0.0, old_heat - cooling)

    state["system_heat"] = new_heat
    state["last_processed_timestamp"] = now
    return old_heat, new_heat

def flatten_parsed(rule_name, values_dict, parent_key=''):
    items = {}
    for k, v in values_dict.items():
        new_key = f"{parent_key}.{k}" if parent_key else f"{rule_name}.{k}"
        if isinstance(v, dict):
            items.update(flatten_parsed(rule_name, v, new_key))
        else:
            items[new_key] = v
    return items

def main(base_dir=None, correlation_id=None):
    if base_dir is None:
        base_dir = os.getcwd()
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    raw_folder = os.path.join(base_dir, 'data', 'raw')
    output_folder = os.path.join(base_dir, 'data', 'output')
    # Use canonical ledger path
    ledger_path = os.path.join(base_dir, 'data', 'ledger.json')

    # Handle legacy path migration if needed (optional but good)
    legacy_ledger_path = os.path.join(base_dir, 'data', 'processed_ledger.json')
    if not os.path.exists(ledger_path) and os.path.exists(legacy_ledger_path):
        os.rename(legacy_ledger_path, ledger_path)

    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # 1) Load State
    state = load_ledger(ledger_path)
    old_heat_at_start = state["system_heat"]
    apply_cooling(state)

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(base_dir, 'rules'))
    except Exception as e:
        log_structured(correlation_id, "load_rules", "error", error=e)
        raise RuleLoadError(f"Could not load rules") from e

    # Read DNA strings
    dna_list = read_input_file(input_file)

    # 2) Load existing outputs for cumulative append
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
                # Migration: 'dna' to 'dna_sequence'
                for entry in parsed_json:
                    if 'dna' in entry:
                        entry['dna_sequence'] = entry.pop('dna')
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
                    # Migration: 'dna' to 'dna_sequence'
                    if 'dna' in all_flattened_keys:
                        all_flattened_keys.remove('dna')
                        all_flattened_keys.add('dna_sequence')

                    for row in reader:
                        if 'dna' in row:
                            row['dna_sequence'] = row.pop('dna')
                        csv_rows.append(row)
        except Exception:
            pass

    new_processed_count = 0
    processed_in_batch = set()

    try:
        for dna_str in dna_list:
            if dna_str in processed_in_batch:
                continue
            processed_in_batch.add(dna_str)

            idempotency_key = dna_str
            if idempotency_key in state["ledger"]:
                log_structured(correlation_id, "dedupe", "dedupe_hit", dna_sequence=idempotency_key)
                continue

            log_structured(correlation_id, "dedupe", "dedupe_miss", dna_sequence=idempotency_key)

            # Thermal Check
            gain = BASE_HEAT_GAIN
            if dna_str.startswith("VOL"):
                gain += VOL_HEAT_PENALTY

            if state["system_heat"] + gain > MAX_HEAT:
                log_structured(correlation_id, "thermal_check", "refusal", dna_sequence=idempotency_key, error=MSG_REFUSAL)
                print(f"[HEAT] {MSG_REFUSAL} {MSG_HINT}")
                raise ThermalOverloadError(MSG_REFUSAL)

            start_time = time.time()
            try:
                result = calculator.parse(dna_str)
                entry = {
                    'dna_sequence': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna_sequence'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"

                state["system_heat"] += gain
                state["last_processed_timestamp"] = time.time()

                log_structured(correlation_id, "parse", "success", dna_sequence=dna_str, latency_ms=int((time.time()-start_time)*1000))

            except RuleParseError as e:
                parsed_json.append({'dna_sequence': dna_str, 'error': str(e)})
                flat = {'dna_sequence': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "error"
                log_structured(correlation_id, "parse", "error", dna_sequence=dna_str, error=e)

            state["ledger"][idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1

    finally:
        # Commit state and output even if failed/interrupted
        if new_processed_count > 0 or state["system_heat"] != old_heat_at_start:
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

                # Write JSON
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)

                # Write CSV
                fieldnames = sorted(all_flattened_keys)
                if 'dna_sequence' in fieldnames:
                    fieldnames.remove('dna_sequence')
                    fieldnames = ['dna_sequence'] + fieldnames

                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        writer.writerow({k: row.get(k, '') for k in fieldnames})

                # Write Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(state, lf, indent=2)

                # Atomic Rename
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            print(f"[OK] Processed {new_processed_count} new items. Heat: {state['system_heat']:.2f}/{MAX_HEAT}")

if __name__ == '__main__':
    main()
