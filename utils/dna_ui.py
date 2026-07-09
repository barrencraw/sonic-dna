#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
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
    """Raised when the system exceeds heat capacity."""
    pass

class DNAStatus:
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# Thermal Fatigue Constants
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0 # units per second

def load_ledger(ledger_path):
    """
    Loads the structured ledger from ledger_path.
    The new format is:
    {
      "system_heat": 0.0,
      "last_processed_timestamp": "ISO TIMESTAMP",
      "ledger": { "dna_str": { "terminal_outcome": "...", ... } }
    }
    """
    default_state = {
        "system_heat": 0.0,
        "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
                # Backward compatibility: if it's a flat dict, wrap it
                if "ledger" not in state:
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "ledger": state
                    }
                return state
        except Exception:
            return default_state
    return default_state

def save_ledger(ledger_path, state):
    """Saves the entire state (heat + ledger) to the JSON file."""
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

    state = load_ledger(ledger_path)
    ledger = state['ledger']

    # Calculate Heat Dissipation
    now = datetime.datetime.now(datetime.timezone.utc)
    last_time = datetime.datetime.fromisoformat(state['last_processed_timestamp'])
    elapsed = (now - last_time).total_seconds()
    if elapsed > 0:
        dissipated = elapsed * COOLING_RATE
        state['system_heat'] = max(0.0, state['system_heat'] - dissipated)
        print(f"[Thermal] {elapsed:.1f}s elapsed, dissipated {dissipated:.1f} heat. Current: {state['system_heat']:.1f}")

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

    new_processed_count = 0
    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            # Thermal Accumulation & Check
            if state['system_heat'] + HEAT_PER_SEQ > MAX_HEAT:
                print(f"[Thermal] REFUSAL_REASON: Thermal Lockout. Heat {state['system_heat']:.1f} + {HEAT_PER_SEQ} > {MAX_HEAT}")
                print(f"[Thermal] NEXT_ACTION_HINT: Wait for dissipation. The system is indifferent to your deadlines.")
                # We do not record REFUSED in the ledger here because we want to retry later
                raise ThermalOverloadError("Thermal Lockout")

            state['system_heat'] += HEAT_PER_SEQ
            print(f"[Thermal] CONSEQUENCE_APPLIED: Heat Accumulation (+{HEAT_PER_SEQ}). Current: {state['system_heat']:.1f}")

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
                outcome = DNAStatus.SUCCESS
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
                outcome = DNAStatus.ERROR

            # Record in ledger
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            new_processed_count += 1
            state['last_processed_timestamp'] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    finally:
        # ATOMIC WRITE PATTERN (Persistence phase)
        # Even if ThermalOverloadError happens, we want to save what we processed so far
        import sys
        handling_exception = sys.exc_info()[1]

        current_on_disk = load_ledger(ledger_path)
        if new_processed_count > 0 or state['system_heat'] != current_on_disk.get('system_heat', -1):
            # 1. Update ledger/state
            # 2. Update JSON/CSV outputs

            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

                try:
                    # Write ledger to temp
                    with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                        json.dump(state, lf, indent=2)
                        lf.flush()
                        os.fsync(lf.fileno())

                    # Write JSON output to temp
                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    # Write CSV output to temp
                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())

                    # Atomic renames (commit)
                    os.replace(tmp_ledger, ledger_path)
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

                except Exception as e:
                    # Don't swallow original exception if one is being handled
                    # If we are handling e.g. ThermalOverloadError, we want to log the persistence error but not raise it
                    # to avoid swallowing the original error.
                    if handling_exception is not None:
                        print(f"[CRITICAL] Persistence failed during cleanup: {e}")
                    else:
                        raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
