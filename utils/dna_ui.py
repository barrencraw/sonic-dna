#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
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

# Thermal Constants
MAX_HEAT = 100.0
HEAT_PER_SEQ = 5.0
COOLING_RATE_PER_SEC = 0.5

def load_ledger(ledger_path):
    default_state = {
        "system_heat": 0.0,
        "last_processed_timestamp": 0.0,
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return default_state
                # Migration: if 'ledger' key is missing, it's old format
                if "ledger" not in data:
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": 0.0,
                        "ledger": data
                    }
                return data
        except Exception:
            return default_state
    return default_state

def save_ledger(ledger_path, state):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
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

    full_state = load_ledger(ledger_path)
    ledger = full_state["ledger"]
    system_heat = full_state.get("system_heat", 0.0)
    last_ts = full_state.get("last_processed_timestamp", 0.0)

    # Cooling logic
    now = time.time()
    if last_ts > 0:
        elapsed = now - last_ts
        cooling = elapsed * COOLING_RATE_PER_SEC
        system_heat = max(0.0, system_heat - cooling)
        print(f"JSON_LOG: {{'step': 'cooling', 'elapsed_sec': {elapsed:.2f}, 'cooling_applied': {cooling:.2f}, 'current_heat': {system_heat:.2f}}}")

    # Load existing output for accumulation
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
        except Exception:
            parsed_json = []

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
    processing_exception = None

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            # Check thermal limit
            if system_heat + HEAT_PER_SEQ > MAX_HEAT:
                print(f"JSON_LOG: {{'step': 'thermal_check', 'outcome': 'refused', 'reason': 'MAX_HEAT reached', 'current_heat': {system_heat:.2f}}}")
                raise ThermalOverloadError(f"System cooling required. Current heat: {system_heat:.2f}")

            system_heat += HEAT_PER_SEQ
            print(f"JSON_LOG: {{'step': 'thermal_increase', 'dna_sequence': '{dna_str}', 'new_heat': {system_heat:.2f}}}")
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
            new_processed_count += 1

    except ThermalOverloadError as e:
        processing_exception = e
    except Exception as e:
        processing_exception = e

    # ATOMIC WRITE PATTERN
    try:
        if new_processed_count > 0:
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

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

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
    except Exception as e:
        # If we already have a processing exception, we might not want to mask it
        # but persistence failure is also critical.
        persistence_err = PersistenceError(f"Failed to write output files atomically: {e}")
        if processing_exception:
            print(f"[CRITICAL] Persistence failed while handling {type(processing_exception).__name__}: {persistence_err}")
            raise processing_exception
        raise persistence_err

    finally:
        # Always update the full state
        full_state["system_heat"] = system_heat
        full_state["last_processed_timestamp"] = time.time()
        full_state["ledger"] = ledger
        save_ledger(ledger_path, full_state)

    if processing_exception:
        raise processing_exception

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
