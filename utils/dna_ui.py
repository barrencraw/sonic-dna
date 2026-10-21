#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# Systemic UI Message Keys (Legibility Pass)
THERMAL_MESSAGE_KEYS = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

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
    """Raised when mainframe core heat exceeds thermal safety limits."""
    def __init__(self, current_heat, threshold):
        self.current_heat = current_heat
        self.threshold = threshold
        self.consequence = THERMAL_MESSAGE_KEYS["consequence_applied"]
        self.reason = THERMAL_MESSAGE_KEYS["refusal_reason"]
        self.hint = THERMAL_MESSAGE_KEYS["next_action_hint"]
        super().__init__(
            f"[{self.reason}] Core heat reached {current_heat:.1f}/{threshold:.1f} ({self.consequence}). "
            f"{self.hint}"
        )

def load_ledger(ledger_path):
    """
    Loads ledger file supporting both structured system state layout and legacy flat ledger dicts.
    Returns (processed_map, system_state_dict).
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and "ledger" in data:
                    ledger_data = data.get("ledger", {})
                    system_state = data.get("system_state", {
                        "core_heat": 0.0,
                        "last_processed_timestamp": None
                    })
                    return ledger_data, system_state
                elif isinstance(data, dict):
                    # Legacy flat layout
                    return data, {"core_heat": 0.0, "last_processed_timestamp": None}
        except Exception:
            return {}, {"core_heat": 0.0, "last_processed_timestamp": None}
    return {}, {"core_heat": 0.0, "last_processed_timestamp": None}

def save_ledger(ledger_path, ledger, system_state):
    try:
        data = {
            "ledger": ledger,
            "system_state": system_state
        }
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        raise PersistenceError(f"Failed to save ledger to {ledger_path}") from e

def calculate_thermal_state(system_state, current_now=None):
    if current_now is None:
        current_now = datetime.datetime.now(datetime.timezone.utc)

    last_time_str = system_state.get("last_processed_timestamp")
    current_heat = float(system_state.get("core_heat", 0.0))

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = (current_now - last_time).total_seconds()
            if elapsed_sec > 0:
                dissipation = elapsed_sec * COOLING_RATE_PER_SEC
                current_heat = max(0.0, current_heat - dissipation)
        except ValueError:
            pass

    return current_heat

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

    ledger, system_state = load_ledger(ledger_path)

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1) Calculate thermal state after cooling dissipation
    core_heat = calculate_thermal_state(system_state, now_utc)

    # Check thermal lockout before starting work
    if core_heat >= THERMAL_LOCKOUT_THRESHOLD:
        system_state["core_heat"] = core_heat
        system_state["last_processed_timestamp"] = now_str
        save_ledger(ledger_path, ledger, system_state)
        raise ThermalOverloadError(core_heat, THERMAL_LOCKOUT_THRESHOLD)

    # 2) Load existing JSON output
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

    # 3) Load existing CSV rows
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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        # Systemic Check: Can mainframe withstand processing next DNA sequence?
        if core_heat + HEAT_PER_SEQUENCE >= THERMAL_LOCKOUT_THRESHOLD:
            system_state["core_heat"] = core_heat
            system_state["last_processed_timestamp"] = now_str
            save_ledger(ledger_path, ledger, system_state)
            raise ThermalOverloadError(core_heat + HEAT_PER_SEQUENCE, THERMAL_LOCKOUT_THRESHOLD)

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
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        core_heat += HEAT_PER_SEQUENCE
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    system_state["core_heat"] = core_heat
    system_state["last_processed_timestamp"] = now_str

    if new_processed_count > 0:
        # Save ledger
        save_ledger(ledger_path, ledger, system_state)

        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)
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
    else:
        # Even if 0 new DNA sequences parsed, persist dissipation timestamp/state
        save_ledger(ledger_path, ledger, system_state)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}. Core heat: {core_heat:.1f}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
