#!/usr/bin/env python3
import os
import json
import csv
import time
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
    """Raised when system heat exceeds threshold."""
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
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

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

def main():
    # Determine file paths
    project_root = os.getcwd()
    data_dir = os.path.join(project_root, 'data')
    raw_folder = os.path.join(data_dir, 'raw')
    output_folder = os.path.join(data_dir, 'output')
    ledger_path = os.path.join(data_dir, 'processed_ledger.json')
    state_path = os.path.join(data_dir, 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    # If not a file, it's okay, maybe we just want to dissipate heat
    dna_list = []
    if os.path.isfile(input_file):
        try:
            dna_list = read_input_file(input_file)
        except Exception as e:
            raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    ledger = load_ledger(ledger_path)
    system_state = load_system_state(state_path)
    system_heat = system_state.get("system_heat", 0.0)

    # PASSIVE DISSIPATION at the start of batch session
    system_heat = max(0.0, system_heat - 0.5)

    if not dna_list:
        # print("[WARN] No DNA strings found in toSequence.txt")
        system_state["system_heat"] = round(system_heat, 2)
        save_system_state(state_path, system_state)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

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

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        if system_heat > 10.0:
            print(f"[REFUSAL] System too hot ({system_heat:.2f} > 10.0). Refusing to process {dna_str}")
            # Raise it so it can be handled by caller or __main__
            raise ThermalOverloadError(f"System Overload: Heat={system_heat:.2f}. Cool-down required.")

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_str)
            rule_name = result['rule']
            values = result['values']

            # CONSEQUENCES
            consequences = []
            if rule_name == 'Volume':
                heat_gain = values['amp'] / 100.0
                system_heat += heat_gain
                consequences.append(f"CONSEQUENCE_APPLIED: Heat increased by {heat_gain:.2f}")

            if rule_name == 'Clarity' and system_heat > 0:
                heat_penalty = int(system_heat)
                # Raising noise floor (N is sign, value is positive integer in dBFS, so N090 is -90)
                # Raising floor means -90 -> -80, so value 90 -> 80.
                old_nf = values['noise_floor']['value']
                values['noise_floor']['value'] = max(0, old_nf - heat_penalty)

                # Increasing THD
                old_thd = values['thd']
                values['thd'] = min(1000, old_thd + heat_penalty * 10)

                consequences.append(f"CONSEQUENCE_APPLIED: Heat penalty applied (Floor: -{values['noise_floor']['value']}dBFS, THD: {values['thd']/100:.2f}%)")

            entry = {
                'dna': dna_str,
                'rule': rule_name,
                'parsed': values
            }
            if consequences:
                entry['system_feedback'] = consequences

            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(rule_name, values)
            flat['dna'] = dna_str
            flat['rule'] = rule_name
            if consequences:
                flat['system_feedback'] = "; ".join(consequences)
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

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

        # Update ledger for each item
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # Update system state
    system_state["system_heat"] = round(system_heat, 2)

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_state = os.path.join(tmp_dir, 'system_state.json')

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

                # 3) Write Ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Write System State to temp
                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump(system_state, sf, indent=2)
                    sf.flush()
                    os.fsync(sf.fileno())

                # 5) Atomic renames
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, state_path)

            except Exception as e:
                raise PersistenceError(f"Failed to write output files atomically: {e}") from e

        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     System Heat: {system_heat:.2f}")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")
    else:
        # If no new strings processed, we still might want to save the dissipated heat
        save_system_state(state_path, system_state)

if __name__ == '__main__':
    try:
        main()
    except ThermalOverloadError as e:
        print(f"[CRITICAL] {e}")
        print("REFUSAL_REASON: Thermal overload threshold exceeded.")
        print("NEXT_ACTION_HINT: Wait for passive dissipation or reduce batch load.")
        import sys
        sys.exit(0)
