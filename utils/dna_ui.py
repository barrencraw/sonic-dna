#!/usr/bin/env python3
import os
import json
import csv
import time
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE_PER_SEC = 0.01

MSG_CONSEQUENCE = "HEAT_AXIS_INCREASED: %0.2f. FANS_ACTIVE."
MSG_REFUSAL = "THERMAL_OVERLOAD: Safety lockout engaged. Batch rejected."
MSG_HINT = "ALLOW_COOLING_PERIOD_OR_REDUCE_SEQUENCE_COUNT."

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    PROCESSING = "processing"

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
    """Raised when proposed batch would exceed thermal limits."""
    pass

def load_ledger(ledger_path):
    default_state = {
        "system_heat": 0.0,
        "last_processed_timestamp": 0.0,
        "ledger": {}
    }
    if not os.path.exists(ledger_path):
        return default_state
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return default_state
            if "ledger" in data:
                return data
            else:
                # Migrate legacy flat format
                default_state["ledger"] = data
                return default_state
    except Exception:
        return default_state

def save_ledger(ledger_path, state):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'ledger.json')
    legacy_ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    if not os.path.exists(ledger_path) and os.path.exists(legacy_ledger_path):
        state = load_ledger(legacy_ledger_path)
    else:
        state = load_ledger(ledger_path)

    ledger = state["ledger"]

    # --- Thermal Cooling ---
    now = time.time()
    last_time = state.get("last_processed_timestamp", 0)
    if last_time > 0:
        elapsed = now - last_time
        cooling = elapsed * COOLING_RATE_PER_SEC
        state["system_heat"] = max(0.0, state["system_heat"] - cooling)

    current_heat = state["system_heat"]

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

    from utils.dna_calculator import RuleParseError

    # --- Batch Refusal Logic (Thermal) ---
    new_dna_sequences = [d for d in dna_list if d not in ledger]
    if not new_dna_sequences:
        print("[Idempotency] All sequences in batch already processed. Skipping.")
        return

    projected_heat = current_heat + (len(new_dna_sequences) * HEAT_PER_ITEM)
    if projected_heat > MAX_HEAT:
        print(f"[FATAL] {MSG_REFUSAL}")
        print(f"        Current heat: {current_heat:0.2f}, Items: {len(new_dna_sequences)}, Projected: {projected_heat:0.2f}")
        print(f"        {MSG_HINT}")
        raise ThermalOverloadError(MSG_REFUSAL)

    new_processed_count = 0
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"{DNAStatus.ERROR.value}: {str(e)}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')

        try:
            # 1) Write JSON output to temp
            with open(tmp_json, 'w', encoding='utf-8') as jf:
                json.dump(parsed_json, jf, indent=2)
                jf.flush()
                os.fsync(jf.fileno())

            # 2) Write CSV output to temp
            fieldnames = sorted(all_flattened_keys)
            with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                writer = csv.DictWriter(cf, fieldnames=fieldnames)
                writer.writeheader()
                for row in csv_rows:
                    out = {k: row.get(k, '') for k in fieldnames}
                    writer.writerow(out)
                cf.flush()
                os.fsync(cf.fileno())

            # 3) Atomic rename (commit)
            # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)

        except Exception as e:
            raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Parsed {len(dna_list)} DNA strings.")

    if new_processed_count > 0:
        # Save ledger
        state["system_heat"] = current_heat + (new_processed_count * HEAT_PER_ITEM)
        state["last_processed_timestamp"] = now
        save_ledger(ledger_path, state)
        print(f"[Thermal] {MSG_CONSEQUENCE % state['system_heat']}")

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
