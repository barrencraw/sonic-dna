#!/usr/bin/env python3
import os
import json
import csv
import time
from datetime import datetime, timezone
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus:
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

UI_MESSAGES = {
    "CONSEQUENCE_APPLIED": "Heat Accumulation",
    "REFUSAL_REASON": "Thermal Lockout",
    "NEXT_ACTION_HINT": "Wait for dissipation. The system is indifferent to your deadlines."
}

HEAT_PER_SEQUENCE = 2.0
MAX_HEAT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing the ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file write fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system heat exceeds thermal safety lockout threshold."""
    def __init__(self, message=UI_MESSAGES["REFUSAL_REASON"]):
        super().__init__(message)
        self.refusal_reason = UI_MESSAGES["REFUSAL_REASON"]
        self.consequence = UI_MESSAGES["CONSEQUENCE_APPLIED"]
        self.next_action_hint = UI_MESSAGES["NEXT_ACTION_HINT"]

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequence_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_sequence_list.append(s)
    return dna_sequence_list

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
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def _write_outputs_atomically(output_folder, json_output_path, csv_output_path, parsed_json, csv_rows, all_flattened_keys):
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
            raise AtomicWriteError("Failed to write output files atomically") from e

def run_batch(correlation_id=None):
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    raw_ledger = load_ledger(ledger_path)
    if isinstance(raw_ledger, dict) and 'ledger' in raw_ledger and 'system_state' in raw_ledger:
        ledger_entries = dict(raw_ledger['ledger'])
        system_state = dict(raw_ledger['system_state'])
    elif isinstance(raw_ledger, dict):
        ledger_entries = dict(raw_ledger)
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}
    else:
        ledger_entries = {}
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}

    now = datetime.now(timezone.utc)
    now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')

    if last_time_str:
        try:
            try:
                last_dt = datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            except ValueError:
                last_dt = datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            elapsed_seconds = max(0.0, (now - last_dt).total_seconds())
            heat_dissipate = elapsed_seconds * COOLING_RATE_PER_SEC
            core_heat = max(0.0, core_heat - heat_dissipate)
        except Exception:
            pass

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

    if core_heat >= MAX_HEAT_THRESHOLD:
        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = now_str
        save_ledger(ledger_path, {'ledger': ledger_entries, 'system_state': system_state})
        raise ThermalOverloadError(UI_MESSAGES["REFUSAL_REASON"])

    new_processed_count = 0
    thermal_lockout_raised = False

    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger_entries:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger_entries[idempotency_key].get('terminal_outcome')}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if core_heat >= MAX_HEAT_THRESHOLD:
            thermal_lockout_raised = True
            break

        try:
            result = calculator.parse(dna_seq)
            entry = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_seq
            flat['dna_sequence'] = dna_seq
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            terminal_outcome = DNAStatus.SUCCESS

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            terminal_outcome = DNAStatus.ERROR

        ledger_entries[idempotency_key] = {
            'terminal_outcome': terminal_outcome,
            'timestamp': now_str
        }
        core_heat += HEAT_PER_SEQUENCE
        new_processed_count += 1

        if core_heat >= MAX_HEAT_THRESHOLD:
            thermal_lockout_raised = True
            break

    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = now_str
    save_ledger(ledger_path, {'ledger': ledger_entries, 'system_state': system_state})

    if new_processed_count > 0:
        _write_outputs_atomically(output_folder, json_output_path, csv_output_path, parsed_json, csv_rows, all_flattened_keys)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Core heat: {core_heat:.1f}")

    if thermal_lockout_raised:
        raise ThermalOverloadError(UI_MESSAGES["REFUSAL_REASON"])

main = run_batch

if __name__ == '__main__':
    main()
