#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys
UI_CONSEQUENCE_APPLIED = "Heat Accumulation"
UI_REFUSAL_REASON = "Thermal Lockout"
UI_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# System Constants
HEAT_PER_SEQUENCE = 2.0
LOCKOUT_THRESHOLD = 10.0
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
    """Raised when the mainframe core heat exceeds lockout threshold."""
    def __init__(self, message=None, core_heat=0.0):
        self.consequence = UI_CONSEQUENCE_APPLIED
        self.refusal_reason = UI_REFUSAL_REASON
        self.next_action_hint = UI_NEXT_ACTION_HINT
        self.core_heat = core_heat
        if not message:
            message = f"{UI_REFUSAL_REASON}: Core heat at {core_heat:.1f}. {UI_NEXT_ACTION_HINT}"
        super().__init__(message)


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
    """
    Loads processed ledger.
    Supports both structured format:
      {'ledger': {...}, 'system_state': {'core_heat': ..., 'last_processed_timestamp': ...}}
    and legacy flat format:
      {dna_str: {...}}
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "ledger" in data and isinstance(data["ledger"], dict):
                        ledger_entries = data["ledger"]
                        system_state = data.get("system_state", {})
                        return ledger_entries, system_state
                    else:
                        # Legacy flat layout
                        return data, {}
        except Exception as e:
            raise PersistenceError(f"Failed to load ledger from {ledger_path}: {e}") from e
    return {}, {}


def save_ledger(ledger_path, ledger_entries, system_state=None):
    if system_state is None:
        system_state = {}
    structured = {
        "ledger": ledger_entries,
        "system_state": system_state
    }
    dir_name = os.path.dirname(ledger_path) or '.'
    ensure_folder(dir_name)
    try:
        with tempfile.TemporaryDirectory(dir=dir_name) as tmp_dir:
            tmp_file = os.path.join(tmp_dir, 'ledger.json')
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(structured, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, ledger_path)
    except Exception as e:
        raise PersistenceError(f"Failed to save ledger: {e}") from e


def run_batch():
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

    ledger, system_state = load_ledger(ledger_path)

    # Compute heat dissipation
    now = datetime.datetime.now(datetime.timezone.utc)
    last_time_str = system_state.get('last_processed_timestamp')
    core_heat = float(system_state.get('core_heat', 0.0))

    if last_time_str:
        try:
            last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = max(0.0, (now - last_dt).total_seconds())
            core_heat = max(0.0, core_heat - (elapsed_sec * COOLING_RATE_PER_SEC))
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
    now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        # Check safety thermal lockout before parsing new sequence
        if core_heat >= LOCKOUT_THRESHOLD:
            system_state['core_heat'] = core_heat
            system_state['last_processed_timestamp'] = now_str
            save_ledger(ledger_path, ledger, system_state)
            raise ThermalOverloadError(
                f"{UI_REFUSAL_REASON}: Core heat at {core_heat:.1f} exceeds threshold {LOCKOUT_THRESHOLD}. {UI_NEXT_ACTION_HINT}",
                core_heat=core_heat
            )

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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
            outcome = f"error: {str(e)}"

        core_heat += HEAT_PER_SEQUENCE
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        new_processed_count += 1

    # Update system state thermal values
    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = now_str

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger, system_state)

        # Atomic write of output JSON and CSV files
        try:
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

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
            raise PersistenceError(f"Failed to write output files atomically: {e}") from e

        print(f"[OK] Processed {new_processed_count} new DNA sequences. Core heat: {core_heat:.1f}")
    else:
        # Save ledger system_state if dissipated heat changed without new sequences
        save_ledger(ledger_path, ledger, system_state)

main = run_batch

if __name__ == '__main__':
    main()
