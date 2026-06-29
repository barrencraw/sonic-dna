#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

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
    """Raised when the system is too hot to process DNA."""
    pass

def log_structured(chain_name, step, outcome, correlation_id=None, actor_id=None, idempotency_key=None, latency_ms=None, error_detail=None, **kwargs):
    """
    Emits a structured JSON log prefixed with JSON_LOG:
    """
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    log_data = {
        "timestamp": timestamp,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
    }
    if correlation_id: log_data["correlation_id"] = correlation_id
    if actor_id: log_data["actor_id"] = actor_id
    if idempotency_key: log_data["idempotency_key"] = idempotency_key
    if latency_ms is not None: log_data["latency_ms"] = round(latency_ms, 2)
    if error_detail: log_data["error_detail"] = error_detail

    # Merge additional kwargs
    log_data.update(kwargs)

    print(f"JSON_LOG: {json.dumps(log_data)}")

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

def main(correlation_id=None, actor_id=None):
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

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    state = load_ledger(ledger_path)
    # Support both old and new ledger formats
    if "ledger" in state:
        ledger = state["ledger"]
        system_heat = state.get("system_heat", 0.0)
        last_ts = state.get("last_processed_timestamp", time.time())
    else:
        ledger = state
        system_heat = 0.0
        last_ts = time.time()

    # Heat dissipation: 0.5 units/sec
    now = time.time()
    elapsed = now - last_ts
    dissipation = elapsed * 0.5
    system_heat = max(0.0, system_heat - dissipation)

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
        item_start_time = time.time()
        outcome = DNAStatus.ERROR.value
        error_detail = None

        if idempotency_key in ledger:
            existing_outcome = ledger[idempotency_key]['terminal_outcome']
            if existing_outcome == DNAStatus.SUCCESS.value:
                log_structured("dna_batch", "idempotency_check", DNAStatus.SKIPPED.value,
                               correlation_id=correlation_id, actor_id=actor_id,
                               idempotency_key=idempotency_key)
                continue

        # Check Thermal Lockout
        if system_heat > 100.0:
            outcome = DNAStatus.REFUSED.value
            hint = "Dissipation required. System indifferent to urgency."
            log_structured("dna_batch", "thermal_check", outcome,
                           correlation_id=correlation_id, actor_id=actor_id,
                           idempotency_key=idempotency_key,
                           reason="Thermal Lockout", hint=hint)

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'reason': "Thermal Lockout",
                'hint': hint
            }
            new_processed_count += 1
            continue

        try:
            # Heat accumulation: +5.0 per sequence
            system_heat += 5.0
            log_structured("dna_batch", "heat_applied", "applied",
                           correlation_id=correlation_id, actor_id=actor_id,
                           idempotency_key=idempotency_key, system_heat=system_heat,
                           message="Heat Accumulation")

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
            outcome = DNAStatus.SUCCESS.value

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
            outcome = DNAStatus.ERROR.value
            error_detail = str(e)

        latency_ms = (time.time() - item_start_time) * 1000
        log_structured("dna_batch", "process_sequence", outcome,
                       correlation_id=correlation_id, actor_id=actor_id,
                       idempotency_key=idempotency_key, latency_ms=latency_ms,
                       error_detail=error_detail if outcome == DNAStatus.ERROR.value else None)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)

        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Write Ledger to temp
                new_state = {
                    "system_heat": system_heat,
                    "last_processed_timestamp": now,
                    "ledger": ledger
                }
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(new_state, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")
    else:
        print("[OK] No new DNA strings to process.")

if __name__ == '__main__':
    main()
