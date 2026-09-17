#!/usr/bin/env python3
import os
import json
import csv
import time
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
    """Raised when system core heat exceeds the safety lockout threshold."""
    def __init__(self, message, consequence, refusal_reason, next_action_hint):
        super().__init__(message)
        self.consequence = consequence
        self.refusal_reason = refusal_reason
        self.next_action_hint = next_action_hint

# UI Message Keys for Thermal Fatigue
UI_MESSAGES = {
    "CONSEQUENCE_APPLIED": "Heat Accumulation",
    "REFUSAL_REASON": "Thermal Lockout",
    "NEXT_ACTION_HINT": "Wait for dissipation. The system is indifferent to your deadlines."
}

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except Exception:
            return {}
    return {}

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

    ledger = load_ledger(ledger_path)

    # Extract system_state from ledger if present, otherwise default
    system_state = ledger.get("_system_state", {"core_heat": 0.0, "last_processed_timestamp": None})
    current_time = time.time()
    last_time = system_state.get("last_processed_timestamp")
    core_heat = system_state.get("core_heat", 0.0)

    if last_time is not None:
        elapsed = max(0.0, current_time - last_time)
        # Heat dissipates at 0.5 units per second
        core_heat = max(0.0, core_heat - (elapsed * 0.5))

    # Thermal Overload Check
    HEAT_THRESHOLD = 10.0
    if core_heat >= HEAT_THRESHOLD:
        msg = f"{UI_MESSAGES['REFUSAL_REASON']}: Core heat at {core_heat:.1f}/{HEAT_THRESHOLD}. {UI_MESSAGES['NEXT_ACTION_HINT']}"
        raise ThermalOverloadError(
            msg,
            consequence=UI_MESSAGES["CONSEQUENCE_APPLIED"],
            refusal_reason=UI_MESSAGES["REFUSAL_REASON"],
            next_action_hint=UI_MESSAGES["NEXT_ACTION_HINT"]
        )

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
    HEAT_PER_SEQUENCE = 2.0

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger and idempotency_key != "_system_state":
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        if core_heat >= HEAT_THRESHOLD:
            msg = f"{UI_MESSAGES['REFUSAL_REASON']}: Threshold reached mid-batch. Core heat at {core_heat:.1f}/{HEAT_THRESHOLD}. {UI_MESSAGES['NEXT_ACTION_HINT']}"
            system_state["core_heat"] = core_heat
            system_state["last_processed_timestamp"] = current_time
            ledger["_system_state"] = system_state
            save_ledger(ledger_path, ledger)
            raise ThermalOverloadError(
                msg,
                consequence=UI_MESSAGES["CONSEQUENCE_APPLIED"],
                refusal_reason=UI_MESSAGES["REFUSAL_REASON"],
                next_action_hint=UI_MESSAGES["NEXT_ACTION_HINT"]
            )

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1
        core_heat += HEAT_PER_SEQUENCE
        print(f"[{UI_MESSAGES['CONSEQUENCE_APPLIED']}] Core heat increased to {core_heat:.1f}")

    system_state["core_heat"] = core_heat
    system_state["last_processed_timestamp"] = current_time
    ledger["_system_state"] = system_state

    if new_processed_count > 0:
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

    total_dna_entries = len([k for k in ledger.keys() if k != "_system_state"])
    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {total_dna_entries}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
