#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input DNA file fails."""
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
    """Raised when atomic file writes fail."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when mainframe core heat exceeds safety lockout threshold."""
    def __init__(self, message="Thermal Lockout: Heat Accumulation limit exceeded. Wait for dissipation. The system is indifferent to your deadlines."):
        super().__init__(message)
        self.consequence_applied = "Heat Accumulation"
        self.refusal_reason = "Thermal Lockout"
        self.next_action_hint = "Wait for dissipation. The system is indifferent to your deadlines."

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequence_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequence_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_path}") from e
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
    """
    Loads ledger file. Returns tuple (ledger_dict, system_state).
    Handles both structured ledger format {'ledger': ..., 'system_state': ...}
    and legacy flat dict format.
    """
    system_state = {
        'core_heat': 0.0,
        'last_processed_timestamp': None
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e

        if isinstance(data, dict):
            if 'ledger' in data and isinstance(data['ledger'], dict):
                ledger_dict = data['ledger']
                if 'system_state' in data and isinstance(data['system_state'], dict):
                    system_state.update(data['system_state'])
                return ledger_dict, system_state
            else:
                return data, system_state
    return {}, system_state

def save_ledger(ledger_path, ledger_dict, system_state=None):
    """
    Saves ledger_dict and system_state to ledger_path in structured format.
    """
    if system_state is None:
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}
    payload = {
        'ledger': ledger_dict,
        'system_state': system_state
    }
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None):
    # Determine file paths
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

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger_dict, system_state = load_ledger(ledger_path)
    initial_ledger_dict = dict(ledger_dict)

    # 1) Calculate thermal dissipation
    current_heat = system_state.get('core_heat', 0.0)
    last_time_str = system_state.get('last_processed_timestamp')
    now = datetime.datetime.now(datetime.timezone.utc)
    now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_time_str:
        try:
            # Parse UTC ISO timestamp
            if 'T' in last_time_str:
                last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            else:
                last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = (now - last_time).total_seconds()
            if elapsed_sec > 0:
                current_heat = max(0.0, current_heat - 0.5 * elapsed_sec)
        except Exception:
            pass

    # Load existing JSON output
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
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger_dict:
            outcome = ledger_dict[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={outcome}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Thermal Fatigue check
        if current_heat + 2.0 > 10.0:
            # Thermal Overload: Save system_state with dissipated core_heat before refusing
            system_state['core_heat'] = current_heat
            system_state['last_processed_timestamp'] = now_str
            save_ledger(ledger_path, initial_ledger_dict, system_state)
            raise ThermalOverloadError(
                f"Thermal Lockout: Heat Accumulation ({current_heat + 2.0:.1f} units) exceeds 10.0 limit. Wait for dissipation. The system is indifferent to your deadlines."
            )

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"{DNAStatus.ERROR.value}: {str(e)}"

        current_heat += 2.0
        ledger_dict[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        new_processed_count += 1

    # Update system state heat and timestamp
    system_state['core_heat'] = current_heat
    system_state['last_processed_timestamp'] = now_str

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
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
                raise AtomicWriteError("Failed to write output files atomically") from e

        # Save ledger
        save_ledger(ledger_path, ledger_dict, system_state)
    else:
        # Even if 0 new items were processed, persist updated thermal dissipation state
        save_ledger(ledger_path, ledger_dict, system_state)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Core heat: {current_heat:.1f}")

main = run_batch

if __name__ == '__main__':
    run_batch()
