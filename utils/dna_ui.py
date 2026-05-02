#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"

class ThermalOverloadError(Exception):
    """Raised when system heat is too high to process Clarity DNA."""
    def __init__(self, heat):
        self.heat = heat
        self.message = f"Core temperature critical: {heat:.2f}H. Clarity processing suspended."
        super().__init__(self.message)

    def to_dict(self):
        return {
            "REFUSAL_REASON": self.message,
            "NEXT_ACTION_HINT": "Allow thermal dissipation. Reduce high-amplitude operations."
        }

def log_observability(outcome, dna=None, details=None, correlation_id=None, actor_id="system"):
    """
    Pipe-delimited telemetry for high searchability.
    """
    payload = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "actor_id": actor_id,
        "correlation_id": correlation_id or "N/A"
    }
    if dna:
        payload["dna"] = dna
    if details:
        payload["details"] = details

    print(f"| TELEMETRY | {json.dumps(payload)}")

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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def load_system_state(state_path):
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"system_heat": 0.0}
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main():
    correlation_id = str(uuid.uuid4())
    log_observability(Outcome.START, correlation_id=correlation_id)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_observability(Outcome.END, details="Input file missing", correlation_id=correlation_id)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(Outcome.ERROR, details=f"Rule load failure: {str(e)}", correlation_id=correlation_id)
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(Outcome.ERROR, details=f"Read failure: {str(e)}", correlation_id=correlation_id)
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        log_observability(Outcome.END, details="Empty input", correlation_id=correlation_id)
        return

    ledger = load_ledger(ledger_path)
    system_state = load_system_state(state_path)
    system_heat = system_state.get("system_heat", 0.0)

    # Natural cooling
    system_heat = max(0.0, system_heat - 0.5)

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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            log_observability(Outcome.SKIPPED, dna=dna_str, details="Already processed", correlation_id=correlation_id)
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            # Heat accumulation from VOL
            if dna_str.startswith("VOL"):
                try:
                    amp_val = int(dna_str[3:7])
                    system_heat += amp_val / 100.0
                except (ValueError, IndexError):
                    pass

            # Clarity (CLA) Consequences
            if dna_str.startswith("CLA"):
                if system_heat > 10.0:
                    raise ThermalOverloadError(system_heat)

            result = calculator.parse(dna_str)

            # Apply penalties if CLA
            if dna_str.startswith("CLA"):
                heat_int = int(system_heat)
                if heat_int > 0:
                    result['values']['noise_floor']['value'] = max(0, result['values']['noise_floor']['value'] - heat_int)
                    result['values']['thd'] = min(1000, result['values']['thd'] + (heat_int * 10))
                    result['CONSEQUENCE_APPLIED'] = f"Thermal noise penalty: floor -{heat_int}dB, THD +{heat_int*0.1:.1f}%"

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            if 'CONSEQUENCE_APPLIED' in result:
                entry['CONSEQUENCE_APPLIED'] = result['CONSEQUENCE_APPLIED']

            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            if 'CONSEQUENCE_APPLIED' in result:
                flat['CONSEQUENCE_APPLIED'] = result['CONSEQUENCE_APPLIED']
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS

        except ThermalOverloadError as toe:
            err_dict = toe.to_dict()
            parsed_json.append({
                'dna': dna_str,
                **err_dict
            })
            flat = {'dna': dna_str, **err_dict}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR
            log_observability(outcome, dna=dna_str, details=err_dict, correlation_id=correlation_id)

        except RuleParseError as rpe:
            parsed_json.append({
                'dna': dna_str,
                'error': str(rpe)
            })
            flat = {'dna': dna_str, 'error': str(rpe)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR
            log_observability(outcome, dna=dna_str, details=str(rpe), correlation_id=correlation_id)

        if outcome == Outcome.SUCCESS:
            log_observability(outcome, dna=dna_str, correlation_id=correlation_id)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.name if isinstance(outcome, Outcome) else outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    # Update state before saving
    system_state["system_heat"] = system_heat

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
                save_ledger(ledger_path, ledger)
                save_system_state(state_path, system_state)

            except Exception as e:
                log_observability(Outcome.ERROR, details=f"Persistence failure: {str(e)}", correlation_id=correlation_id)
                raise PersistenceError("Failed to write output files atomically") from e

        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    else:
        # Save state even if no new items processed (for cooling)
        save_system_state(state_path, system_state)
        print("[OK] No new DNA strings to process.")

    log_observability(Outcome.END, details=f"Processed {new_processed_count} items. Heat: {system_heat:.2f}", correlation_id=correlation_id)

if __name__ == '__main__':
    main()
