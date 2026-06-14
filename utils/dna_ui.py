#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Constants ---
MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE_PER_SEC = 0.01

# --- UI Messages (Indifferent Tone) ---
MSG_CONSEQUENCE = "System heat increased. Thermal drift may affect precision."
MSG_REFUSAL = "Hardware safety lockout. Thermal threshold exceeded."
MSG_HINT = "Wait for natural dissipation. Cooling is constant."

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    PROCESSING = "processing"
    DEDUPE = "dedupe_hit"

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
    """Raised when system heat is too high to process more items."""
    pass

def log_structured(step, outcome, correlation_id, dna_sequence=None, idempotency_key=None, start_time=None, actor_id='system'):
    latency_ms = None
    if start_time:
        latency_ms = int((time.time() - start_time) * 1000)

    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome,
        "actor_id": actor_id
    }
    if dna_sequence:
        log_entry["dna_sequence"] = dna_sequence
    if idempotency_key:
        log_entry["idempotency_key"] = idempotency_key
    if latency_ms is not None:
        log_entry["latency_ms"] = latency_ms

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
    # Migration: check for legacy processed_ledger.json
    legacy_path = os.path.join(os.path.dirname(ledger_path), 'processed_ledger.json')
    if not os.path.exists(ledger_path) and os.path.exists(legacy_path):
        os.rename(legacy_path, ledger_path)

    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
                # Check if it's the new structured state
                if isinstance(state, dict) and "ledger" in state:
                    return state
                else:
                    # Wrap legacy flat ledger
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": time.time(),
                        "ledger": state
                    }
        except Exception:
            pass

    return {
        "system_heat": 0.0,
        "last_processed_timestamp": time.time(),
        "ledger": {}
    }

def apply_cooling(state):
    last_ts = state.get("last_processed_timestamp", time.time())
    current_heat = state.get("system_heat", 0.0)
    elapsed = time.time() - last_ts
    if elapsed > 0:
        cooling = elapsed * COOLING_RATE_PER_SEC
        state["system_heat"] = max(0.0, current_heat - cooling)
    state["last_processed_timestamp"] = time.time()
    return state

def main(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    dna_list = read_input_file(input_file)

    state = load_ledger(ledger_path)
    old_heat = state["system_heat"]
    state = apply_cooling(state)

    if not dna_list:
        # We still want to apply cooling even if no items are processed
        if state["system_heat"] != old_heat:
            with open(ledger_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules: {e}")

    ledger = state["ledger"]

    # Thermal pre-check
    potential_new_items = 0
    for dna_str in dna_list:
        if dna_str not in ledger:
            potential_new_items += 1

    if state["system_heat"] + (potential_new_items * HEAT_PER_ITEM) > MAX_HEAT:
        log_structured("thermal_check", f"{DNAStatus.ERROR.value}: {MSG_REFUSAL}", correlation_id)
        # Still persist the cooling we just applied
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        raise ThermalOverloadError(f"{MSG_REFUSAL} {MSG_HINT}")

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    # Load existing data to append
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                # Migration: rename 'dna' to 'dna_sequence' in existing data
                for entry in parsed_json:
                    if 'dna' in entry:
                        entry['dna_sequence'] = entry.pop('dna')
        except Exception:
            pass

    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as cf:
                reader = csv.DictReader(cf)
                if reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    # Migration: rename 'dna' in fieldnames
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
            start_time = time.time()
            if dna_str in ledger:
                log_structured("parse_item", DNAStatus.DEDUPE.value, correlation_id, dna_sequence=dna_str, idempotency_key=dna_str)
                continue

            if dna_str in processed_in_batch:
                continue
            processed_in_batch.add(dna_str)

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

                outcome = DNAStatus.SUCCESS.value
                state["system_heat"] += HEAT_PER_ITEM
                print(f"[CONSEQUENCE] {MSG_CONSEQUENCE} Heat: {state['system_heat']:.2f}")

            except RuleParseError as e:
                outcome = DNAStatus.ERROR.value
                parsed_json.append({'dna_sequence': dna_str, 'error': str(e)})
                flat = {'dna_sequence': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

            ledger[dna_str] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1
            log_structured("parse_item", outcome, correlation_id, dna_sequence=dna_str, idempotency_key=dna_str, start_time=start_time)

    finally:
        # Atomic Write Block
        if new_processed_count > 0 or state["system_heat"] != old_heat:
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
                        json.dump(state, lf, indent=2)
                        lf.flush()
                        os.fsync(lf.fileno())

                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)
                    os.replace(tmp_ledger, ledger_path)
                except Exception as e:
                    # Re-raise to ensure caller knows about failure
                    if isinstance(e, PersistenceError):
                        raise
                    raise PersistenceError(f"Atomic commit failed: {e}") from e

    print(f"[OK] Processed {new_processed_count} new DNA strings. Heat: {state['system_heat']:.2f}")

if __name__ == '__main__':
    main()
