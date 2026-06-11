#!/usr/bin/env python3
import os
import json
import csv
import time
from utils.dna_calculator import DNACalculator, RuleParseError

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

class ThermalOverloadError(DNAProcessingError):
    """Raised when the system heat exceeds MAX_HEAT."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

# --- Thermal Fatigue Constants ---
MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE = 0.0083  # Units per second (~1 unit every 2 minutes)

# --- UI Message Keys (Indifferent Tone) ---
MSG_CONSEQUENCE = "Thermal accumulation detected. Hardware degradation imminent."
MSG_REFUSAL = "Safety lockout active. Thermal threshold exceeded."
MSG_HINT = "Initiate cooling cycle. System remains indifferent to urgency."

def load_ledger(ledger_path):
    """
    Loads the ledger and system state (heat, timestamp).
    Migrates legacy flat-dict ledgers to structured state.
    """
    state = {
        "system_heat": 0.0,
        "last_processed_timestamp": 0.0,
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "ledger" in data:
                    state.update(data)
                else:
                    # Migration from legacy flat dict
                    state["ledger"] = data
        except Exception:
            pass
    return state

def save_ledger(ledger_path, state):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def log_structured(step, outcome, correlation_id=None, idempotency_key=None, latency_ms=None, actor_id="system", extra=None):
    """
    Standardized JSON logging for automated parsing.
    """
    log_obj = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "chain_name": "dna_batch_processor",
        "step": step,
        "outcome": outcome,
        "actor_id": actor_id,
    }
    if correlation_id:
        log_obj["correlation_id"] = correlation_id
    if idempotency_key:
        log_obj["idempotency_key"] = idempotency_key
    if latency_ms is not None:
        log_obj["latency_ms"] = latency_ms
    if extra:
        log_obj.update(extra)

    print(f"JSON_LOG: {json.dumps(log_obj)}")

def apply_cooling(state):
    """
    Calculates heat dissipation based on time elapsed since last processing.
    """
    now = time.time()
    last_time = state.get("last_processed_timestamp", now)
    elapsed = now - last_time

    current_heat = state.get("system_heat", 0.0)
    cooling = elapsed * COOLING_RATE
    new_heat = max(0.0, current_heat - cooling)

    state["system_heat"] = new_heat
    state["last_processed_timestamp"] = now
    return state

def main(base_dir=None, correlation_id=None):
    if base_dir is None:
        base_dir = os.getcwd()

    # Determine file paths
    raw_folder = os.path.join(base_dir, 'data', 'raw')
    output_folder = os.path.join(base_dir, 'data', 'output')

    # Migration: Rename legacy ledger if it exists
    legacy_ledger_path = os.path.join(base_dir, 'data', 'processed_ledger.json')
    ledger_path = os.path.join(base_dir, 'data', 'ledger.json')
    if os.path.exists(legacy_ledger_path) and not os.path.exists(ledger_path):
        os.rename(legacy_ledger_path, ledger_path)

    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        # Even if file is missing, we might want to apply cooling
        state = load_ledger(ledger_path)
        old_heat = state["system_heat"]
        state = apply_cooling(state)
        if state["system_heat"] != old_heat:
            save_ledger(ledger_path, state)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(base_dir, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(base_dir, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        # Same here, apply cooling if idle
        state = load_ledger(ledger_path)
        old_heat = state["system_heat"]
        state = apply_cooling(state)
        if state["system_heat"] != old_heat:
            save_ledger(ledger_path, state)
        return

    log_structured("batch_start", "success", correlation_id, extra={"count": len(dna_list)})

    state = load_ledger(ledger_path)
    old_heat = state["system_heat"]
    state = apply_cooling(state)
    ledger = state["ledger"]

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
                # Migration: rename 'dna' to 'dna_sequence'
                for entry in parsed_json:
                    if 'dna' in entry:
                        entry['dna_sequence'] = entry.pop('dna')
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
                    # Migration: rename 'dna' to 'dna_sequence' in header
                    if 'dna' in all_flattened_keys:
                        all_flattened_keys.remove('dna')
                        all_flattened_keys.add('dna_sequence')
                    csv_rows = list(reader)
                    for row in csv_rows:
                        if 'dna' in row:
                            row['dna_sequence'] = row.pop('dna')
        except Exception:
            pass

    processed_in_batch = set()
    new_processed_count = 0

    try:
        for dna_str in dna_list:
            start_time = time.time()
            idempotency_key = dna_str
            if idempotency_key in ledger or idempotency_key in processed_in_batch:
                log_structured("deduplication", "skipped", correlation_id, idempotency_key)
                continue

            # Thermal refusal check BEFORE processing
            if state["system_heat"] + HEAT_PER_ITEM > MAX_HEAT:
                log_structured("thermal_check", "refusal", correlation_id, idempotency_key,
                               extra={"system_heat": state["system_heat"], "msg": MSG_REFUSAL})
                raise ThermalOverloadError(MSG_REFUSAL)

            # Record heat cost for attempting
            state["system_heat"] += HEAT_PER_ITEM
            if state["system_heat"] > MAX_HEAT * 0.7:
                log_structured("thermal_warning", "consequence", correlation_id, idempotency_key,
                               extra={"system_heat": state["system_heat"], "msg": MSG_CONSEQUENCE})

            try:
                result = calculator.parse(dna_str)
                entry = {
                    'dna_sequence': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna_sequence'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"

            except RuleParseError as e:
                parsed_json.append({
                    'dna_sequence': dna_str,
                    'error': str(e)
                })
                flat = {'dna_sequence': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = f"error: {str(e)}"

            latency = int((time.time() - start_time) * 1000)
            # Commit item to ledger and batch set
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            processed_in_batch.add(idempotency_key)
            new_processed_count += 1
            log_structured("dna_parse", outcome, correlation_id, idempotency_key, latency_ms=latency)

    finally:
        # ATOMIC WRITE PATTERN for outputs AND state
        if new_processed_count > 0 or state["system_heat"] != old_heat:
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

                try:
                    # 1) Write Ledger to temp
                    with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                        json.dump(state, lf, indent=2)
                        lf.flush()
                        os.fsync(lf.fileno())

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

                    # 4) Atomic renames
                    os.replace(tmp_ledger, ledger_path)
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

                except Exception as e:
                    # If this fails, we have a persistence problem
                    log_structured("persistence", "error", correlation_id, extra={"error": str(e)})
                    raise PersistenceError(f"Failed to write output files atomically: {e}") from e

    if new_processed_count > 0:
        log_structured("batch_end", "success", correlation_id, extra={"new_processed": new_processed_count, "total_ledger": len(ledger)})
    elif state["system_heat"] != old_heat:
        log_structured("system_idle", "cooling", correlation_id, extra={"heat": state["system_heat"]})

if __name__ == '__main__':
    main()
