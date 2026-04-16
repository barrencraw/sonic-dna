#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
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
    """Raised when system heat exceeds safety threshold."""
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
    if not os.path.exists(input_path):
        return []
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

def main(data_dir=None):
    # Determine file paths
    project_root = os.getcwd()
    if data_dir:
        base_dir = data_dir
    else:
        base_dir = os.path.join(project_root, 'data')

    raw_folder = os.path.join(base_dir, 'raw')
    output_folder = os.path.join(base_dir, 'output')
    ledger_path = os.path.join(base_dir, 'processed_ledger.json')
    state_path = os.path.join(base_dir, 'system_state.json')

    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    rules_folder = os.path.join(project_root, 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {rules_folder}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)

    # Load Thermal State
    system_heat = 0.0
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r') as sf:
                state = json.load(sf)
                system_heat = state.get('system_heat', 0.0)
        except Exception:
            system_heat = 0.0

    # Natural cooling at start of batch (only if we have work or explicitly asked to run)
    if dna_list and system_heat > 0:
        system_heat = max(0.0, system_heat - 1.0)
        print(f"[Thermal] Natural cooling applied. Current heat: {system_heat:.2f}")

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
    work_actually_done = False

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            # FATIGUE PRE-CHECK
            if dna_str.startswith('CLA'):
                if system_heat > 10.0:
                    print(f"[Thermal] REFUSAL_REASON: THERMAL_OVERLOAD (Heat: {system_heat:.2f}). NEXT_ACTION_HINT: DISSIPATION_REQUIRED.")
                    raise ThermalOverloadError(f"Core temperature exceeds safety threshold (10.0).")

            result = calculator.parse(dna_str)

            # FATIGUE CONSEQUENCE (CLA)
            if result['rule'] == 'Clarity':
                penalty = int(system_heat)
                if penalty > 0:
                    # In Clarity rule, noise_floor is signed N + 3 digits.
                    # value is absolute dBFS (e.g. 90). Subtracting penalty reduces clarity (e.g. 85dBFS floor).
                    orig = result['values']['noise_floor']['value']
                    result['values']['noise_floor']['value'] = max(0, orig - penalty)
                    print(f"[Thermal] CONSEQUENCE_APPLIED: THERMAL_NOISE_PENALTY: +{penalty}dB noise floor elevation.")

            # FATIGUE ACCUMULATION (VOL)
            if result['rule'] == 'Volume':
                amp = result['values']['amp']
                heat_gain = amp / 100.0
                system_heat += heat_gain
                print(f"[Thermal] HEAT_INCREASE: +{heat_gain:.2f} (New Total: {system_heat:.2f})")

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

        except (RuleParseError, ThermalOverloadError) as e:
            outcome = f"error: {str(e)}"
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        # Update ledger inside the loop for each processed DNA
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1
        work_actually_done = True

    if work_actually_done:
        # ATOMIC WRITE PATTERN:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_state = os.path.join(tmp_dir, 'state.json')

            try:
                # JSON
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # State
                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump({'system_heat': system_heat}, sf, indent=2)
                    sf.flush()
                    os.fsync(sf.fileno())

                # Commit
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, state_path)
            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    # Even if no new DNA was processed (all hits), we might have cooled the system.
    # If dna_list was not empty, we applied cooling and potentially processed new DNA.
    if dna_list and not work_actually_done:
        # We had a list of DNA, but they were all dedupe hits.
        # We still applied cooling! We should save the state.
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_state = os.path.join(tmp_dir, 'state.json')
            try:
                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump({'system_heat': system_heat}, sf, indent=2)
                    sf.flush()
                    os.fsync(sf.fileno())
                os.replace(tmp_state, state_path)
            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    if dna_list:
        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")
        print(f"     State (Heat) → {system_heat:.2f}")

if __name__ == '__main__':
    main()
