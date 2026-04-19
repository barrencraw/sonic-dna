#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
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
    """Raised when system heat is too high to process certain DNA."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if os.path.exists(input_path):
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

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def load_system_state(state_path):
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main(data_dir=None):
    # Determine file paths
    project_root = data_dir if data_dir else os.getcwd()
    data_folder = os.path.join(project_root, 'data')
    raw_folder = os.path.join(data_folder, 'raw')
    output_folder = os.path.join(data_folder, 'output')
    ledger_path = os.path.join(data_folder, 'processed_ledger.json')
    state_path = os.path.join(data_folder, 'system_state.json')

    ensure_folder(data_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

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

    ledger = load_ledger(ledger_path)
    state = load_system_state(state_path)

    # Natural cooling
    old_heat = state.get("system_heat", 0.0)
    state["system_heat"] = max(0.0, old_heat - 1.0)
    if state["system_heat"] != old_heat:
        print(f"[System] Natural cooling applied: {old_heat:.2f} -> {state['system_heat']:.2f}")

    # Load existing results to append
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

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_str)
            rule = result['rule']
            values = result['values']

            # Fatigue Logic: Thermal Gain from Volume
            if rule == "Volume":
                amp = values.get("amp", 0)
                gain = amp / 100.0
                state["system_heat"] += gain
                print(f"[Fatigue] Heat gain: +{gain:.2f} (from Volume amp={amp})")

            # Fatigue Logic: Thermal Penalty/Refusal for Clarity
            penalty_msg = None
            if rule == "Clarity":
                if state["system_heat"] > 10.0:
                    msg = "Thermal overload: System too hot to maintain clarity."
                    hint = "Cool down the system by processing non-VOL DNA or waiting."
                    print(f"[Fatigue] REFUSAL_REASON: {msg}")
                    print(f"[Fatigue] NEXT_ACTION_HINT: {hint}")
                    raise ThermalOverloadError(msg)

                if state["system_heat"] > 0:
                    penalty = int(state["system_heat"])
                    old_noise = values.get("noise_floor", {}).get("value", 0)
                    # Reducing the value of noise_floor (which is N + value, e.g. N090 -> -90dB)
                    # Making it "less negative" means raising the floor.
                    values["noise_floor"]["value"] = max(0, old_noise - penalty)
                    penalty_msg = f"Thermal noise added: noise_floor reduced by {penalty} due to system_heat ({state['system_heat']:.2f})"
                    print(f"[Fatigue] CONSEQUENCE_APPLIED: {penalty_msg}")

            entry = {
                'dna': dna_str,
                'rule': rule,
                'parsed': values
            }
            if penalty_msg:
                entry['consequence'] = penalty_msg
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(rule, values)
            flat['dna'] = dna_str
            flat['rule'] = rule
            if penalty_msg:
                flat['consequence'] = penalty_msg
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except (RuleParseError, ThermalOverloadError) as e:
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        # Update ledger
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # ATOMIC WRITE PATTERN
    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
        tmp_state = os.path.join(tmp_dir, 'system_state.json')

        try:
            if new_processed_count > 0:
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
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            # Always save system state if we had input (cooling or heating happened)
            with open(tmp_state, 'w', encoding='utf-8') as sf:
                json.dump(state, sf, indent=2)
                sf.flush()
                os.fsync(sf.fileno())
            os.replace(tmp_state, state_path)

        except Exception as e:
            raise PersistenceError("Failed to write output files atomically") from e

    if new_processed_count > 0:
        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     JSON \u2192 {json_output_path}")
        print(f"     CSV  \u2192 {csv_output_path}")
    else:
        print("[OK] No new DNA strings to process.")

if __name__ == '__main__':
    main()
