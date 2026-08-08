#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
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

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when writing or moving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing or moving output files atomically fails."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when the core temperature exceeds the safety threshold."""
    pass

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    dir_name = os.path.dirname(ledger_path) or os.getcwd()
    tmp_path = None
    tmp_file = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".ledger_", suffix=".tmp")
        tmp_file = os.fdopen(fd, 'w', encoding='utf-8')
        json.dump(ledger, tmp_file, indent=2)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
        tmp_file.close()
        tmp_file = None
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        if tmp_file is not None:
            try:
                tmp_file.close()
            except Exception:
                pass
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise LedgerSaveError(f"Could not save ledger atomically to {ledger_path}") from e

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
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    ledger_data = load_ledger(ledger_path)
    if isinstance(ledger_data, dict) and "ledger" in ledger_data:
        ledger = ledger_data["ledger"]
        system_state = ledger_data.get("system_state", {})
    else:
        ledger = ledger_data if isinstance(ledger_data, dict) else {}
        system_state = {}

    # Calculate heat dissipation (0.5 units/sec passive core cooling)
    current_time = datetime.datetime.now(datetime.timezone.utc)

    last_heat = system_state.get("core_heat", 0.0)
    last_time_str = system_state.get("last_processed_timestamp", None)

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = (current_time - last_time).total_seconds()
            dissipated_heat = elapsed_seconds * 0.5
            current_heat = max(0.0, last_heat - dissipated_heat)
        except Exception:
            current_heat = last_heat
    else:
        current_heat = 0.0

    system_state["core_heat"] = current_heat

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        if current_heat != last_heat:
            system_state["core_heat"] = current_heat
            system_state["last_processed_timestamp"] = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')
            ledger_data_to_save = {
                "ledger": ledger,
                "system_state": system_state
            }
            save_ledger(ledger_path, ledger_data_to_save)
        return

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
    error_occurred = False
    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            # Lockout check right before processing a new item
            if current_heat >= 10.0:
                print(f"[Thermal Lockout] Core temperature of {current_heat:.1f} exceeds safety threshold. All operations suspended.")
                print("Wait for dissipation. The system is indifferent to your deadlines.")
                raise ThermalOverloadError(
                    f"Thermal Lockout: Core temperature of {current_heat:.1f} exceeds safety threshold. "
                    "Wait for dissipation. The system is indifferent to your deadlines."
                )

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
                outcome = "success"
                current_heat += 2.0
                print(f"Heat Accumulation: Core heat is now {current_heat:.1f}/10.0.")

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
                outcome = f"error: {str(e)}"
                current_heat += 1.0
                print(f"Heat Accumulation: Core heat is now {current_heat:.1f}/10.0.")

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
            new_processed_count += 1

            # Record last processed timestamp
            current_time = datetime.datetime.now(datetime.timezone.utc)
            system_state["core_heat"] = current_heat
            system_state["last_processed_timestamp"] = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    except Exception as e:
        error_occurred = True
        raise
    finally:
        # Save ledger if any new sequences processed OR core heat cooled down passively
        if new_processed_count > 0 or current_heat != last_heat:
            system_state["core_heat"] = current_heat
            if new_processed_count == 0:
                # Passive cooling cycle only. Record current UTC time as last processed.
                system_state["last_processed_timestamp"] = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')

            ledger_data_to_save = {
                "ledger": ledger,
                "system_state": system_state
            }
            try:
                save_ledger(ledger_path, ledger_data_to_save)
            except Exception as save_err:
                if not error_occurred:
                    raise save_err

        # Write output files atomically only if new items processed
        if new_processed_count > 0:
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
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

                except Exception as write_err:
                    if not error_occurred:
                        raise AtomicWriteError("Failed to write output files atomically") from write_err

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
