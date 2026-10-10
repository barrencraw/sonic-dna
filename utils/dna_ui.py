#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# Systemic Message Keys (UI Legibility Pass)
MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# Thermal Constants
HEAT_PER_SEQUENCE = 2.0
COOLING_RATE_PER_SEC = 0.5
THERMAL_LOCKOUT_THRESHOLD = 10.0

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
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
    """Raised when processing exceeds thermal capacity lockout threshold."""
    def __init__(self, current_heat, limit):
        super().__init__(f"[{MSG_REFUSAL_REASON}] Core heat reached {current_heat:.1f}/{limit:.1f}. {MSG_NEXT_ACTION_HINT}")
        self.current_heat = current_heat
        self.limit = limit
        self.consequence = MSG_CONSEQUENCE_APPLIED
        self.refusal_reason = MSG_REFUSAL_REASON
        self.next_action_hint = MSG_NEXT_ACTION_HINT

def load_ledger(ledger_path):
    """
    Loads ledger file.
    Supports both legacy flat ledgers `{key: entry}` and structured state
    `{'ledger': {key: entry}, 'system_state': {'core_heat': float, 'last_processed_timestamp': str}}`.
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if 'ledger' in data and 'system_state' in data:
                        return data
                    else:
                        return {'ledger': data, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}
        except Exception:
            return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}
    return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}

def save_ledger(ledger_path, ledger_data):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger_data, f, indent=2)

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

    # Read DNA sequences
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    full_ledger_data = load_ledger(ledger_path)
    ledger = full_ledger_data.get('ledger', {})
    system_state = full_ledger_data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})

    current_time_dt = datetime.datetime.now(datetime.timezone.utc)
    current_time_str = current_time_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Heat decay calculation
    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')
    if last_time_str:
        try:
            last_time_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = max(0.0, (current_time_dt - last_time_dt).total_seconds())
            heat_dissipated = elapsed_sec * COOLING_RATE_PER_SEC
            core_heat = max(0.0, core_heat - heat_dissipated)
        except Exception:
            pass

    # Load existing JSON output
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

    # Load existing CSV rows
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
    thermal_lockout_triggered = False

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Check thermal limits before processing sequence
        if core_heat >= THERMAL_LOCKOUT_THRESHOLD:
            print(f"[{MSG_REFUSAL_REASON}] Heat threshold reached ({core_heat:.1f}/{THERMAL_LOCKOUT_THRESHOLD}). {MSG_NEXT_ACTION_HINT}")
            thermal_lockout_triggered = True
            break

        # Process DNA sequence
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

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        # Heat Accumulation (Consequence applied)
        core_heat += HEAT_PER_SEQUENCE
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': current_time_str
        }
        print(f"[{MSG_CONSEQUENCE_APPLIED}] +{HEAT_PER_SEQUENCE} core heat (Total: {core_heat:.1f}/{THERMAL_LOCKOUT_THRESHOLD})")
        new_processed_count += 1

    # Save system state and ledger if sequences were processed or lockout occurred
    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = current_time_str
    full_ledger_data = {'ledger': ledger, 'system_state': system_state}

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
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

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

        save_ledger(ledger_path, full_ledger_data)
        print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")
    else:
        # Persist heat/time state even if 0 sequences were newly added
        save_ledger(ledger_path, full_ledger_data)

    if thermal_lockout_triggered:
        raise ThermalOverloadError(core_heat, THERMAL_LOCKOUT_THRESHOLD)

if __name__ == '__main__':
    main()
