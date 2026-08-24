#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys (Indifferent Tone)
MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# Systemic Parameters
MAX_HEAT = 10.0
HEAT_PER_SEQUENCE = 2.0
COOLING_RATE_PER_SEC = 0.5


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
    """Raised when processing exceeds thermal capacity thresholds."""
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
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            return {}
    return {}


def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)


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

    ledger = load_ledger(ledger_path)

    # Load / initialize system thermal state
    now = time.time()
    system_state = ledger.get('system_state', {
        'core_heat': 0.0,
        'last_processed_timestamp': now
    })
    last_time = system_state.get('last_processed_timestamp', now)
    elapsed = max(0.0, now - last_time)
    current_heat = max(0.0, float(system_state.get('core_heat', 0.0)) - (elapsed * COOLING_RATE_PER_SEC))

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

    # Filter out already-processed items and duplicates within batch
    unique_unprocessed = []
    for dna in dna_list:
        if dna != 'system_state' and dna not in ledger and dna not in unique_unprocessed:
            unique_unprocessed.append(dna)

    if not unique_unprocessed:
        # All items are deduplicated, update thermal state with dissipation
        system_state['core_heat'] = current_heat
        system_state['last_processed_timestamp'] = now
        ledger['system_state'] = system_state
        save_ledger(ledger_path, ledger)
        print("[Idempotency] All inputs deduplicated. No new processing required.")
        return

    # Check thermal capacity for new processing batch
    projected_heat = current_heat + (len(unique_unprocessed) * HEAT_PER_SEQUENCE)

    if projected_heat > MAX_HEAT:
        system_state['core_heat'] = current_heat
        system_state['last_processed_timestamp'] = now
        ledger['system_state'] = system_state
        save_ledger(ledger_path, ledger)
        refusal_msg = f"[{MSG_REFUSAL_REASON}] Heat load {projected_heat:.1f} exceeds safety threshold {MAX_HEAT:.1f}. {MSG_NEXT_ACTION_HINT}"
        print(f"[ERROR] {refusal_msg}")
        raise ThermalOverloadError(refusal_msg)

    # Process unique unprocessed DNA strings
    new_processed_count = 0
    for dna_str in unique_unprocessed:
        print(f"[Idempotency] key={dna_str} dedupe_hit=False terminal_outcome=processing")
        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        ledger[dna_str] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        current_heat += HEAT_PER_SEQUENCE
        new_processed_count += 1
        print(f"[{MSG_CONSEQUENCE_APPLIED}] Core thermal load: {current_heat:.1f}/{MAX_HEAT:.1f} heat units.")

    # Update thermal state
    system_state['core_heat'] = current_heat
    system_state['last_processed_timestamp'] = now
    ledger['system_state'] = system_state

    # ATOMIC WRITE PATTERN:
    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')

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

            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)

        except Exception as e:
            raise PersistenceError("Failed to write output files atomically") from e

    save_ledger(ledger_path, ledger)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger) - 1}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")


if __name__ == '__main__':
    main()
