#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus:
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

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
    """Raised when loading or parsing the ledger file fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when mainframe temperature exceeds safety lockout threshold."""
    def __init__(self, message="Thermal Lockout", core_heat=10.0, threshold=10.0):
        super().__init__(message)
        self.consequence_applied = "Heat Accumulation"
        self.refusal_reason = "Thermal Lockout"
        self.next_action_hint = "Wait for dissipation. The system is indifferent to your deadlines."
        self.core_heat = core_heat
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
        except Exception as e:
            raise LedgerLoadError(f"Failed to parse ledger file: {ledger_path}") from e

        if isinstance(data, dict) and 'ledger' in data and 'system_state' in data:
            return data
        elif isinstance(data, dict):
            # Legacy flat ledger dictionary format
            return {
                'ledger': data,
                'system_state': {
                    'core_heat': 0.0,
                    'last_processed_timestamp': None
                }
            }
        else:
            raise LedgerLoadError(f"Invalid ledger format in {ledger_path}")
    return {
        'ledger': {},
        'system_state': {
            'core_heat': 0.0,
            'last_processed_timestamp': None
        }
    }

def save_ledger(ledger_path, ledger_data):
    output_dir = os.path.dirname(os.path.abspath(ledger_path))
    ensure_folder(output_dir)
    with tempfile.TemporaryDirectory(dir=output_dir) as tmp_dir:
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
        with open(tmp_ledger, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_ledger, ledger_path)

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
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger_data = load_ledger(ledger_path)
    ledger_map = ledger_data.get('ledger', {})
    system_state = ledger_data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})

    initial_ledger_map = dict(ledger_map)

    # Core heat dissipation calculation
    core_heat = float(system_state.get('core_heat', 0.0))
    last_ts_str = system_state.get('last_processed_timestamp')

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_ts_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_ts_str:
        try:
            last_dt = datetime.datetime.strptime(last_ts_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = max(0.0, (now_utc - last_dt).total_seconds())
            dissipated = elapsed_sec * 0.5
            core_heat = max(0.0, core_heat - dissipated)
        except Exception:
            pass

    # 1) Load existing JSON output
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
        if idempotency_key in ledger_map:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger_map[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if core_heat + 2.0 > 10.0 or core_heat >= 10.0:
            system_state['core_heat'] = core_heat
            system_state['last_processed_timestamp'] = now_ts_str
            save_ledger(ledger_path, {
                'ledger': initial_ledger_map,
                'system_state': system_state
            })
            raise ThermalOverloadError(
                message="Thermal Lockout: Heat Accumulation exceeded safety threshold. Wait for dissipation. The system is indifferent to your deadlines.",
                core_heat=core_heat,
                threshold=10.0
            )

        core_heat += 2.0

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
            outcome = DNAStatus.SUCCESS

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'dna_sequence': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

        ledger_map[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = now_ts_str

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
                raise PersistenceError("Failed to write output files atomically") from e

    save_ledger(ledger_path, {
        'ledger': ledger_map,
        'system_state': system_state
    })

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger_map)}")

main = run_batch

if __name__ == '__main__':
    main()
