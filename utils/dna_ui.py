#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

CONSEQUENCE_APPLIED = "Heat Accumulation"
REFUSAL_REASON = "Thermal Lockout"
NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input file cannot be read."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when reading ledger fails or ledger is corrupted."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file replacement fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal fatigue safety threshold is exceeded."""
    def __init__(self, message="Thermal Lockout", heat=0.0, threshold=10.0):
        super().__init__(message)
        self.consequence_applied = CONSEQUENCE_APPLIED
        self.refusal_reason = REFUSAL_REASON
        self.next_action_hint = NEXT_ACTION_HINT
        self.current_heat = heat
        self.threshold = threshold

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_path}") from e
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
                return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}") from e
    return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger at {ledger_path}") from e

def run_batch(correlation_id=None):
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
    dna_list = read_input_file(input_file)

    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    raw_ledger = load_ledger(ledger_path)
    if 'ledger' in raw_ledger:
        entries = raw_ledger['ledger']
        system_state = raw_ledger.get('system_state', {})
    else:
        entries = raw_ledger
        system_state = {}

    now = datetime.datetime.now(datetime.timezone.utc)
    now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (now - last_time).total_seconds())
            core_heat = max(0.0, core_heat - elapsed_seconds * 0.5)
        except ValueError:
            pass

    # Load existing output files if they exist
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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in entries:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={entries[idempotency_key].get('terminal_outcome')}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if core_heat + 2.0 > 10.0:
            updated_ledger = {
                'ledger': entries,
                'system_state': {
                    'core_heat': core_heat,
                    'last_processed_timestamp': now_str
                }
            }
            save_ledger(ledger_path, updated_ledger)
            raise ThermalOverloadError(
                message=REFUSAL_REASON,
                heat=core_heat + 2.0,
                threshold=10.0
            )

        try:
            result = calculator.parse(dna_sequence=dna_str)
            entry = {
                'dna': dna_str,
                'dna_sequence': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['dna_sequence'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"
        except RuleParseError as e:
            entry = {
                'dna': dna_str,
                'dna_sequence': dna_str,
                'error': str(e)
            }
            parsed_json.append(entry)
            flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        core_heat += 2.0
        new_processed_count += 1

    updated_ledger = {
        'ledger': entries,
        'system_state': {
            'core_heat': core_heat,
            'last_processed_timestamp': now_str
        }
    }

    if new_processed_count > 0:
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

        save_ledger(ledger_path, updated_ledger)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(entries)}")

main = run_batch

if __name__ == '__main__':
    run_batch()
