#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
from utils.dna_calculator import DNACalculator, RuleParseError

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

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file replace fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system core heat threshold (10.0) is exceeded."""
    CONSEQUENCE_APPLIED = "Heat Accumulation"
    REFUSAL_REASON = "Thermal Lockout"
    NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

    def __init__(self, message=None):
        if message is None:
            message = f"{self.REFUSAL_REASON}: {self.CONSEQUENCE_APPLIED}. {self.NEXT_ACTION_HINT}"
        super().__init__(message)


def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if 'ledger' in data and 'system_state' in data:
                        return data['ledger'], data['system_state']
                    else:
                        # Legacy flat ledger format
                        return data, {'core_heat': 0.0, 'last_processed_timestamp': None}
                return {}, {'core_heat': 0.0, 'last_processed_timestamp': None}
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}") from e
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger: {e}") from e
    return {}, {'core_heat': 0.0, 'last_processed_timestamp': None}

def save_ledger(ledger_path, ledger, system_state):
    try:
        data = {
            'ledger': ledger,
            'system_state': system_state
        }
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch():
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    ensure_folder(output_folder)

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
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger, system_state = load_ledger(ledger_path)

    # Calculate thermal decay
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    current_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')

    if last_time_str:
        try:
            last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (now_utc - last_dt).total_seconds())
            decayed_heat = elapsed_seconds * 0.5
            current_heat = max(0.0, current_heat - decayed_heat)
        except Exception:
            pass

    system_state['core_heat'] = current_heat

    # Load existing output files for cumulative updates
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
    try:
        for dna_str in dna_sequence_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            # Thermal overload check prior to adding heat
            if current_heat + 2.0 > 10.0:
                system_state['core_heat'] = current_heat
                system_state['last_processed_timestamp'] = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
                raise ThermalOverloadError()

            try:
                result = calculator.parse(dna_str)
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
                parsed_json.append({
                    'dna': dna_str,
                    'dna_sequence': dna_str,
                    'error': str(e)
                })
                flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "error"

            current_heat += 2.0
            system_state['core_heat'] = current_heat
            system_state['last_processed_timestamp'] = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1

    finally:
        # Atomic commit of processed batch and system state
        save_ledger(ledger_path, ledger, system_state)

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

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    main()
