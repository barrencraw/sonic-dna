#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

# System UI Message Keys
MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# System Constraints & Thresholds
HEAT_PER_SEQUENCE = 2.0
HEAT_DISSIPATION_RATE = 0.5  # Heat units decayed per second
HEAT_LOCKOUT_THRESHOLD = 10.0  # Max core heat threshold

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
    """Raised when processing exceeds the thermal lockout threshold."""
    def __init__(self, message=None, current_heat=0.0, lockout_threshold=HEAT_LOCKOUT_THRESHOLD):
        if message is None:
            message = f"{MSG_REFUSAL_REASON}: {MSG_CONSEQUENCE_APPLIED} reached {current_heat:.1f}/{lockout_threshold:.1f}. {MSG_NEXT_ACTION_HINT}"
        super().__init__(message)
        self.current_heat = current_heat
        self.lockout_threshold = lockout_threshold

def parse_iso_utc(ts_str):
    if not ts_str:
        return None
    try:
        if ts_str.endswith('Z'):
            ts_str = ts_str[:-1] + '+00:00'
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None

def load_ledger(ledger_path):
    default_state = {'core_heat': 0.0, 'last_processed_timestamp': None}
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if 'ledger' in data and isinstance(data['ledger'], dict):
                        ledger_entries = dict(data['ledger'])
                        system_state = data.get('system_state', default_state)
                        return ledger_entries, system_state
                    else:
                        entries = dict(data)
                        system_state = entries.pop('_system_state', default_state)
                        return entries, system_state
        except Exception:
            return {}, default_state
    return {}, default_state

def save_ledger(ledger_path, ledger, system_state=None):
    if system_state is None:
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}
    payload = dict(ledger)
    payload['_system_state'] = system_state
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)

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

    ledger, system_state = load_ledger(ledger_path)

    # Compute heat dissipation since last processed timestamp
    now_utc = datetime.now(timezone.utc)
    stored_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')
    last_dt = parse_iso_utc(last_time_str)

    if last_dt:
        elapsed_seconds = max(0.0, (now_utc - last_dt).total_seconds())
        current_heat = max(0.0, stored_heat - (elapsed_seconds * HEAT_DISSIPATION_RATE))
    else:
        current_heat = stored_heat

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
    lockout_exception = None

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Check candidate heat against lockout threshold
        candidate_heat = current_heat + HEAT_PER_SEQUENCE
        if candidate_heat >= HEAT_LOCKOUT_THRESHOLD:
            print(f"[{MSG_REFUSAL_REASON}] Core heat level at {current_heat:.1f} + {HEAT_PER_SEQUENCE:.1f} = {candidate_heat:.1f} >= threshold {HEAT_LOCKOUT_THRESHOLD:.1f}. {MSG_NEXT_ACTION_HINT}")
            lockout_exception = ThermalOverloadError(
                message=f"{MSG_REFUSAL_REASON}: {MSG_CONSEQUENCE_APPLIED} reached {candidate_heat:.1f}/{HEAT_LOCKOUT_THRESHOLD:.1f}. {MSG_NEXT_ACTION_HINT}",
                current_heat=current_heat,
                lockout_threshold=HEAT_LOCKOUT_THRESHOLD
            )
            break

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

        current_heat = candidate_heat
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # Update system_state
    system_state = {
        'core_heat': current_heat,
        'last_processed_timestamp': now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    }

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
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

        # Save ledger with system state
        save_ledger(ledger_path, ledger, system_state)
    else:
        # Even if 0 new processed sequences, persist dissipated system_state
        save_ledger(ledger_path, ledger, system_state)

    if lockout_exception:
        raise lockout_exception

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
