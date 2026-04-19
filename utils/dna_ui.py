#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import getpass
from enum import Enum
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    NO_NEW_DNA = "NO_NEW_DNA"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"

def log_observability(chain_name, step, outcome, correlation_id=None, latency_ms=0, idempotency_key=None, error_message=None):
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "latency_ms": latency_ms,
        "actor_id": getpass.getuser(),
    }
    if idempotency_key:
        log_entry["idempotency_key"] = idempotency_key
    if error_message:
        log_entry["error_message"] = error_message

    print(f"[Observability] {json.dumps(log_entry)}")

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

import tempfile
import shutil

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
    """Raised when system heat exceeds threshold."""
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

def main(data_dir=None):
    start_time = time.time()
    correlation_id = str(uuid.uuid4())
    chain_name = "dna_batch_chain"

    log_observability(chain_name, "START", Outcome.START, correlation_id=correlation_id)

    # Determine file paths
    project_root = data_dir if data_dir else os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_observability(chain_name, "END", Outcome.ERROR, correlation_id=correlation_id, latency_ms=int((time.time() - start_time) * 1000), error_message=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(chain_name, "END", Outcome.ERROR, correlation_id=correlation_id, latency_ms=int((time.time() - start_time) * 1000), error_message=f"Could not load rules: {str(e)}")
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(chain_name, "END", Outcome.ERROR, correlation_id=correlation_id, latency_ms=int((time.time() - start_time) * 1000), error_message=f"Failed to read input file: {str(e)}")
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        log_observability(chain_name, "END", Outcome.NO_NEW_DNA, correlation_id=correlation_id, latency_ms=int((time.time() - start_time) * 1000))
        return

    # Load Thermal State
    system_heat = 0.0
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as sf:
                state_data = json.load(sf)
                system_heat = state_data.get('system_heat', 0.0)
        except Exception:
            pass

    # Natural cooling: -1.0 per batch run
    system_heat = max(0.0, system_heat - 1.0)
    print(f"[Fatigue] Initial system_heat={system_heat:.2f} (after natural cooling)")

    ledger = load_ledger(ledger_path)

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
    item_outcomes = []
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
        log_observability(chain_name, "ITEM_PROCESS", Outcome.PROCESSING, correlation_id=correlation_id, idempotency_key=idempotency_key)

        item_outcome = Outcome.ERROR
        try:
            result = calculator.parse(dna_str)
            rule_name = result['rule']
            vals = result['values']

            # Fatigue logic
            if rule_name == 'Volume':
                # amp / 100 heat gain
                amp = vals.get('amp', 0)
                heat_gain = amp / 100.0
                system_heat += heat_gain
                print(f"[Fatigue] Volume DNA processed. amp={amp}, heat_gain=+{heat_gain:.2f}, total_heat={system_heat:.2f}")

            if rule_name == 'Clarity':
                # Penalty or refusal
                if system_heat > 10.0:
                    raise ThermalOverloadError(f"System heat {system_heat:.2f} exceeds threshold 10.0 for Clarity parsing.")

                # Apply penalty: raise noise floor (less negative)
                # noise_floor is encoded as N + positive value (e.g. N090 = -90dBFS)
                # To raise the floor (penalty), we DECREASE the positive value (e.g. 90 -> 80)
                if 'noise_floor' in vals:
                    nf_val = vals['noise_floor'].get('value', 0)
                    penalty = int(system_heat)
                    vals['noise_floor']['value'] = max(0, nf_val - penalty)
                    print(f"[Fatigue] Clarity DNA penalized. heat={system_heat:.2f}, noise_floor_penalty=-{penalty}, new_nf_val={vals['noise_floor']['value']}")
                    # Add hint for next action
                    vals['CONSEQUENCE_APPLIED'] = f"Thermal noise penalty of +{penalty} applied to noise floor."
                    vals['NEXT_ACTION_HINT'] = "Wait for natural cooling or process lower-amplitude signals."

            entry = {
                'dna': dna_str,
                'rule': rule_name,
                'parsed': vals
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome_str = "success"
            item_outcome = Outcome.SUCCESS

        except (RuleParseError, ThermalOverloadError) as e:
            # On parse error or thermal refusal, record as error entry
            error_type = "ThermalRefusal" if isinstance(e, ThermalOverloadError) else "ParseError"
            parsed_json.append({
                'dna': dna_str,
                'error': str(e),
                'error_type': error_type
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e), 'error_type': error_type}
            if isinstance(e, ThermalOverloadError):
                flat['REFUSAL_REASON'] = str(e)
                flat['NEXT_ACTION_HINT'] = "Allow system to cool before re-attempting Clarity parsing."

            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome_str = f"error: {str(e)}"
            item_outcome = Outcome.ERROR

        ledger[idempotency_key] = {
            'terminal_outcome': outcome_str,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome_str}")
        log_observability(chain_name, "ITEM_PROCESS", item_outcome, correlation_id=correlation_id, idempotency_key=idempotency_key, error_message=outcome_str if item_outcome == Outcome.ERROR else None)
        new_processed_count += 1
        item_outcomes.append(item_outcome)

    if new_processed_count > 0 or dna_list:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)

        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'processed_ledger.json')

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

                # 3) Write Ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Write System State to temp
                with open(os.path.join(tmp_dir, 'system_state.json'), 'w', encoding='utf-8') as sf:
                    json.dump({'system_heat': system_heat}, sf, indent=2)

                # 5) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(os.path.join(tmp_dir, 'system_state.json'), state_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

    if not item_outcomes:
        final_outcome = Outcome.SKIPPED
    elif all(o == Outcome.SUCCESS for o in item_outcomes):
        final_outcome = Outcome.SUCCESS
    elif all(o == Outcome.ERROR for o in item_outcomes):
        final_outcome = Outcome.ERROR
    else:
        final_outcome = Outcome.PARTIAL_SUCCESS

    log_observability(chain_name, "END", final_outcome, correlation_id=correlation_id, latency_ms=int((time.time() - start_time) * 1000))

    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
