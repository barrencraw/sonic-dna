#!/usr/bin/env python3
import os
import json
import csv
import time
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

# Thermal Constants
MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE_PER_SEC = 0.01

class ThermalOverloadError(Exception):
    """Raised when system heat exceeds MAX_HEAT."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def log_structured(step, outcome, correlation_id, dna_sequence=None, latency_ms=None, error_detail=None):
    """
    Standardized JSON logging for the DNA batch chain.
    """
    log_obj = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_processing",
        "step": step,
        "outcome": outcome,
        "actor_id": "system"
    }
    if dna_sequence:
        log_obj["idempotency_key"] = dna_sequence
    if latency_ms is not None:
        log_obj["latency_ms"] = latency_ms
    if error_detail:
        log_obj["error_detail"] = error_detail

    print(f"JSON_LOG:{json.dumps(log_obj)}")

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if not os.path.exists(input_path):
        return []
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

def load_ledger(ledger_path, legacy_ledger_path=None):
    """
    Loads ledger.json. Migrates from processed_ledger.json if ledger.json is missing.
    Returns structured state: {"system_heat": 0.0, "last_processed_timestamp": None, "ledger": {}}
    """
    state = {
        "system_heat": 0.0,
        "last_processed_timestamp": None,
        "ledger": {}
    }

    target_path = ledger_path
    if not os.path.exists(target_path) and legacy_ledger_path and os.path.exists(legacy_ledger_path):
        try:
            os.rename(legacy_ledger_path, target_path)
            print(f"[Migration] Renamed {legacy_ledger_path} to {target_path}")
        except Exception as e:
            print(f"[Migration] Failed to rename legacy ledger: {e}")

    if os.path.exists(target_path):
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # If it's the old flat dictionary format, wrap it
                if "ledger" not in data:
                    state["ledger"] = data
                else:
                    state = data
        except Exception:
            pass
    return state

def apply_cooling(state):
    """
    Applies cooling based on elapsed time since last_processed_timestamp.
    """
    last_ts = state.get("last_processed_timestamp")
    if last_ts:
        elapsed = time.time() - last_ts
        cooling = elapsed * COOLING_RATE_PER_SEC
        state["system_heat"] = max(0.0, state["system_heat"] - cooling)
    state["last_processed_timestamp"] = time.time()

def main(base_dir=None, correlation_id="manual-run"):
    # Determine file paths
    project_root = base_dir or os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'ledger.json')
    legacy_ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    log_structured("start", "success", correlation_id)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured("read_input", "error", correlation_id, error_detail=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured("load_rules", "error", correlation_id, error_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured("read_input", "error", correlation_id, error_detail=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured("process_batch", "success", correlation_id, error_detail="No DNA strings found")
        return

    state = load_ledger(ledger_path, legacy_ledger_path)
    old_heat = state["system_heat"]
    apply_cooling(state)
    ledger = state["ledger"]

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                raw_parsed = json.load(jf)
                if isinstance(raw_parsed, list):
                    for entry in raw_parsed:
                        if 'dna' in entry:
                            entry['dna_sequence'] = entry.pop('dna')
                    parsed_json = raw_parsed
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
                    new_fieldnames = [f if f != 'dna' else 'dna_sequence' for f in reader.fieldnames]
                    all_flattened_keys = set(new_fieldnames)
                    for row in reader:
                        if 'dna' in row:
                            row['dna_sequence'] = row.pop('dna')
                        csv_rows.append(row)
        except Exception:
            pass

    new_processed_count = 0
    try:
        for dna_sequence_str in dna_list:
            step_start = time.time()
            idempotency_key = dna_sequence_str
            if idempotency_key in ledger:
                log_structured("parse", "skipped", correlation_id, dna_sequence=idempotency_key)
                continue

            # Thermal Fatigue Check
            if state["system_heat"] + HEAT_PER_ITEM > MAX_HEAT:
                log_structured("thermal_check", "error", correlation_id, error_detail="Thermal Overload")
                raise ThermalOverloadError("Hardware safety lockout: System heat exceeded threshold.")

            try:
                result = calculator.parse(dna_sequence_str)
                entry = {
                    'dna_sequence': dna_sequence_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna_sequence'] = dna_sequence_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"
                error_detail = None

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna_sequence': dna_sequence_str,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna_sequence': dna_sequence_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "error"
                error_detail = str(e)

            state["system_heat"] += HEAT_PER_ITEM
            latency_ms = (time.time() - step_start) * 1000
            log_structured("parse", outcome, correlation_id, dna_sequence=dna_sequence_str, latency_ms=latency_ms, error_detail=error_detail)

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1
    finally:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)

        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

        if new_processed_count > 0 or state["system_heat"] != old_heat:
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

                try:
                    # 1) Write JSON output to temp
                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    # 2) Write CSV output to temp
                    fieldnames = sorted(all_flattened_keys)
                    # Ensure 'dna_sequence' and 'rule' are at the front if possible
                    if 'rule' in fieldnames:
                        fieldnames.remove('rule')
                        fieldnames.insert(0, 'rule')
                    if 'dna_sequence' in fieldnames:
                        fieldnames.remove('dna_sequence')
                        fieldnames.insert(0, 'dna_sequence')

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
                        json.dump(state, lf, indent=2)
                        lf.flush()
                        os.fsync(lf.fileno())

                    # 4) Atomic rename (commit)
                    # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)
                    os.replace(tmp_ledger, ledger_path)

                except Exception as e:
                    log_structured("persist", "error", correlation_id, error_detail=str(e))
                    raise PersistenceError("Failed to write output files atomically") from e

    log_structured("end", "success", correlation_id)

if __name__ == '__main__':
    main()
