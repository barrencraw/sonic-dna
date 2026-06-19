#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Constants & Enums ---
MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE_PER_SEC = 0.01

MSG_CONSEQUENCE = "System is cooling down. Please wait."
MSG_REFUSAL = "Thermal overload! Batch refused."
MSG_HINT = "Try smaller batches or wait for cooling."

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    PROCESSING = "processing"

def log_structured(step, outcome, correlation_id=None, chain_name="dna_batch", actor_id="system", start_time=None):
    """Standardized structured logging for the DNA batch chain."""
    latency_ms = None
    if start_time:
        latency_ms = round((time.time() - start_time) * 1000, 2)

    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "actor_id": actor_id
    }
    if latency_ms is not None:
        log_entry["latency_ms"] = latency_ms

    print(f"JSON_LOG: {json.dumps(log_entry)}")

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

class ThermalOverloadError(DNAProcessingError):
    """Raised when system heat exceeds MAX_HEAT."""
    pass
def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Migration: if it's just a dict mapping, it's the legacy format
                if "ledger" not in data:
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": time.time(),
                        "ledger": data
                    }
                return data
        except Exception:
            pass
    return {"system_heat": 0.0, "last_processed_timestamp": time.time(), "ledger": {}}

def main(correlation_id=None, chain_name="dna_batch"):
    start_time = time.time()
    log_structured("batch_start", "processing", correlation_id=correlation_id, chain_name=chain_name)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured("batch_end", "error", correlation_id=correlation_id, chain_name=chain_name, start_time=start_time)
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured("batch_end", "error", correlation_id=correlation_id, chain_name=chain_name, start_time=start_time)
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured("batch_end", "error", correlation_id=correlation_id, chain_name=chain_name, start_time=start_time)
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured("batch_end", "success", correlation_id=correlation_id, chain_name=chain_name, start_time=start_time)
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    full_state = load_ledger(ledger_path)
    system_heat = full_state.get("system_heat", 0.0)
    last_ts = full_state.get("last_processed_timestamp", time.time())
    ledger = full_state.get("ledger", {})

    # Deterministic Cooling
    elapsed = time.time() - last_ts
    cooling = elapsed * COOLING_RATE_PER_SEC
    system_heat = max(0.0, system_heat - cooling)

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
    outcome = "unknown_error"

    try:
        for dna_str in dna_list:
            step_start = time.time()
            idempotency_key = dna_str

            if idempotency_key in ledger:
                log_structured("item_process", DNAStatus.SKIPPED.value,
                               correlation_id=correlation_id, chain_name=chain_name, start_time=step_start)
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            # Thermal Check
            if system_heat >= MAX_HEAT:
                print(f"[FATIGUE] {MSG_REFUSAL} heat={system_heat:.2f}")
                print(f"          {MSG_CONSEQUENCE} {MSG_HINT}")
                raise ThermalOverloadError(f"{MSG_REFUSAL} heat={system_heat:.2f}")

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            try:
                result = calculator.parse(dna_str)
                entry = {
                    'dna_sequence': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna_sequence'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.SUCCESS.value

            except RuleParseError as e:
                parsed_json.append({
                    'dna_sequence': dna_str,
                    'error': str(e)
                })
                flat = {'dna_sequence': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR.value

            system_heat += HEAT_PER_ITEM
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            log_structured("item_process", outcome,
                           correlation_id=correlation_id, chain_name=chain_name, start_time=step_start)
            new_processed_count += 1

    finally:
        # Atomic persistence of all state
        full_state["system_heat"] = system_heat
        full_state["last_processed_timestamp"] = time.time()
        full_state["ledger"] = ledger

        with tempfile.TemporaryDirectory(dir=os.path.dirname(ledger_path)) as tmp_dir:
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            try:
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(full_state, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

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

                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    log_structured("batch_end", "success", correlation_id=correlation_id, chain_name=chain_name, start_time=start_time)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
