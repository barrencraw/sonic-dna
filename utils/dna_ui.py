#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import datetime
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys for systemic feedback (Fatigue / Thermal Pressure Axis)
MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# Deterministic Thermal Constants
HEAT_PER_SEQUENCE = 2.0
DISSIPATION_RATE_PER_SEC = 0.5  # Dissipates 0.5 heat per second
MAX_HEAT_THRESHOLD = 10.0       # Lockout if heat >= threshold

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
    """
    Raised when sequencer hardware reaches maximum thermal threshold.
    Increases consequence density: the system refuses execution and locks out until cooled.
    """
    def __init__(self, current_heat, required_dissipation):
        self.consequence_applied = MSG_CONSEQUENCE_APPLIED
        self.refusal_reason = MSG_REFUSAL_REASON
        self.next_action_hint = MSG_NEXT_ACTION_HINT
        self.current_heat = current_heat
        self.required_dissipation = required_dissipation
        super().__init__(
            f"[{self.refusal_reason}] {self.consequence_applied}: Core temperature {current_heat:.1f} >= {MAX_HEAT_THRESHOLD:.1f}. "
            f"{self.next_action_hint}"
        )

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
    """
    Loads ledger supporting both legacy flat dict format:
      { "DNA1": {...} }
    and structured format with system_state:
      { "ledger": { "DNA1": {...} }, "system_state": { "core_heat": float, "last_processed_timestamp": str } }
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "ledger" in data and isinstance(data["ledger"], dict):
                        return data
                    return {"ledger": data, "system_state": {"core_heat": 0.0, "last_processed_timestamp": None}}
        except Exception:
            return {"ledger": {}, "system_state": {"core_heat": 0.0, "last_processed_timestamp": None}}
    return {"ledger": {}, "system_state": {"core_heat": 0.0, "last_processed_timestamp": None}}

def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
    except Exception as e:
        raise PersistenceError(f"Failed to save ledger: {e}") from e

def calculate_current_heat(system_state, now_utc):
    """
    Calculates dissipated heat deterministically based on elapsed physical seconds.
    """
    core_heat = float(system_state.get('core_heat', 0.0))
    last_timestamp_str = system_state.get('last_processed_timestamp')

    if last_timestamp_str:
        try:
            last_dt = datetime.datetime.fromisoformat(last_timestamp_str)
            elapsed = (now_utc - last_dt).total_seconds()
            if elapsed > 0:
                dissipation = elapsed * DISSIPATION_RATE_PER_SEC
                core_heat = max(0.0, core_heat - dissipation)
        except Exception:
            pass
    return core_heat

def commit_atomic_outputs(output_folder, parsed_json, csv_rows, all_flattened_keys):
    """Atomically commits JSON and CSV outputs."""
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

def main():
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
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
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    full_ledger_data = load_ledger(ledger_path)
    ledger = full_ledger_data.get('ledger', {})
    system_state = full_ledger_data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    current_heat = calculate_current_heat(system_state, now_utc)

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
    refusal_error = None
    processed_this_run = []

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        # Systemic Fatigue / Consequence Check
        if current_heat >= MAX_HEAT_THRESHOLD:
            # System Lockout reached
            refusal_error = ThermalOverloadError(
                current_heat=current_heat,
                required_dissipation=(current_heat - MAX_HEAT_THRESHOLD)
            )
            print(f"[{refusal_error.refusal_reason}] {refusal_error.consequence_applied}: Sequence rejected. {refusal_error.next_action_hint}")
            break

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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

        # Apply deterministic consequence: heat accumulation
        current_heat += HEAT_PER_SEQUENCE
        print(f"[{MSG_CONSEQUENCE_APPLIED}] Processed {dna_str} → Core Heat: {current_heat:.1f}/{MAX_HEAT_THRESHOLD:.1f}")

        timestamp_str = now_utc.isoformat()
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': timestamp_str
        }
        processed_this_run.append(idempotency_key)
        new_processed_count += 1

    # Atomically write output files FIRST if new items were processed
    if new_processed_count > 0:
        commit_atomic_outputs(output_folder, parsed_json, csv_rows, all_flattened_keys)

    # Update system thermal state and save ledger
    system_state['core_heat'] = current_heat
    system_state['last_processed_timestamp'] = now_utc.isoformat()
    full_ledger_data['ledger'] = ledger
    full_ledger_data['system_state'] = system_state

    save_ledger(ledger_path, full_ledger_data)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}. System Core Heat: {current_heat:.1f}")

    if refusal_error is not None:
        # If thermal lockout occurred, raise to notify caller (e.g. main.py / watcher)
        # unparsed items remain in toSequence.txt because caller will catch the error and skip clearing
        raise refusal_error

if __name__ == '__main__':
    main()
