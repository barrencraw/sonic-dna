#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
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

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing JSON or CSV output files atomically fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when the safety heat threshold is exceeded."""
    pass

def log_structured(step, outcome, correlation_id=None, actor_id="mainframe", chain_name="dna_batch_parsing", latency_ms=0, idempotency_key=None, outcome_detail=None):
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or "N/A"
    }
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {}
                return data
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    ledger_dir = os.path.dirname(ledger_path)
    try:
        fd, temp_path = tempfile.mkstemp(dir=ledger_dir, prefix="ledger_", suffix=".json")
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(ledger, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, ledger_path)
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger atomically to {ledger_path}") from e

def run_batch(correlation_id=None):
    start_time_ms = int(time.time() * 1000)
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
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)

    # 1) Calculate thermal dissipation
    current_time = datetime.datetime.now(datetime.timezone.utc)
    current_time_str = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    system_heat = ledger.get('system_heat', ledger.get('_system_heat', 0.0))
    last_time_str = ledger.get('last_processed_timestamp', ledger.get('_last_processed_timestamp', ''))

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = (current_time - last_time).total_seconds()
            if elapsed_seconds > 0:
                dissipated_heat = elapsed_seconds * 0.5
                system_heat = max(0.0, system_heat - dissipated_heat)
        except Exception:
            pass

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
    thermal_lockout_occurred = False

    for dna_str in dna_list:
        idempotency_key = dna_str

        # Check if already exists in ledger (support flat and structured)
        existing_outcome = None
        if idempotency_key in ledger:
            existing_outcome = ledger[idempotency_key].get('terminal_outcome') if isinstance(ledger[idempotency_key], dict) else None
        elif 'ledger' in ledger and isinstance(ledger['ledger'], dict) and idempotency_key in ledger['ledger']:
            existing_outcome = ledger['ledger'][idempotency_key].get('terminal_outcome')

        if existing_outcome in [DNAStatus.SUCCESS, DNAStatus.ERROR, "success", "error"]:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={existing_outcome}")
            log_structured("skip", "skipped", correlation_id, idempotency_key=idempotency_key, outcome_detail="dedupe_hit")
            continue

        # Check for thermal lockout before processing any new item
        if system_heat >= 10.0:
            thermal_lockout_occurred = True
            log_structured("lockout_check", "refused", correlation_id, idempotency_key=idempotency_key, outcome_detail="Thermal Lockout")
            break

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna_sequence': dna_str,
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_str
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS
            system_heat += 2.0
            log_structured("parse", "success", correlation_id, idempotency_key=idempotency_key, outcome_detail=f"Heat Accumulation: mainframe temperature is rising. Current heat: {system_heat:.1f}°C.")

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna_sequence': dna_str,
                'dna': dna_str,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna_sequence': dna_str, 'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR
            log_structured("parse", "error", correlation_id, idempotency_key=idempotency_key, outcome_detail=str(e))

        entry_data = {
            'terminal_outcome': outcome,
            'timestamp': current_time_str
        }
        ledger[idempotency_key] = entry_data
        if 'ledger' not in ledger:
            ledger['ledger'] = {}
        ledger['ledger'][idempotency_key] = entry_data

        new_processed_count += 1

    # Record updated system heat and timestamp in ledger
    ledger['system_heat'] = system_heat
    ledger['_system_heat'] = system_heat
    ledger['last_processed_timestamp'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    ledger['_last_processed_timestamp'] = ledger['last_processed_timestamp']

    print(f"[OK] Parsed {len(dna_list)} DNA strings.")

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
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
                raise AtomicWriteError("Failed to write output files atomically") from e

    # Always save ledger (even if 0 new sequences, to persist thermal cooling/timestamp)
    save_ledger(ledger_path, ledger)

    end_time_ms = int(time.time() * 1000)
    latency_ms = end_time_ms - start_time_ms
    log_structured("batch_complete", "success", correlation_id, latency_ms=latency_ms)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger.get('ledger', ledger))}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

    if thermal_lockout_occurred:
        raise ThermalOverloadError(
            "Thermal Lockout: safety heat threshold exceeded. Operation refused. "
            "Wait for dissipation. The system is indifferent to your deadlines."
        )

main = run_batch

if __name__ == '__main__':
    main()
