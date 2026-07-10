#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
import uuid
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Constants ---
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0  # units per second

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
    """Raised when system exceeds thermal limits."""
    pass

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
                # Handle legacy flat ledger format if necessary
                if 'ledger' not in data:
                    return {
                        'system_heat': 0.0,
                        'last_processed_timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        'ledger': data
                    }
                return data
        except Exception:
            pass
    return {
        'system_heat': 0.0,
        'last_processed_timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'ledger': {}
    }

def log_structured(correlation_id, step, outcome, latency_ms=0, actor_id="system", chain_name="dna_batch_parsing", idempotency_key=None):
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms
    }
    if idempotency_key:
        log_entry["idempotency_key"] = idempotency_key
    print(f"JSON_LOG:{json.dumps(log_entry)}")

def main(correlation_id=None, actor_id="system"):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    start_time = time.time()
    log_structured(correlation_id, "start", "initiated", actor_id=actor_id)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, "end", "error", latency_ms=int((time.time()-start_time)*1000), actor_id=actor_id)
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, "end", "error", latency_ms=int((time.time()-start_time)*1000), actor_id=actor_id)
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, "end", "error", latency_ms=int((time.time()-start_time)*1000), actor_id=actor_id)
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    state = load_ledger(ledger_path)
    ledger = state['ledger']
    current_heat = state.get('system_heat', 0.0)
    last_time_str = state.get('last_processed_timestamp')

    # Dissipate heat
    heat_before_dissipation = current_heat
    if last_time_str:
        try:
            last_ts = datetime.datetime.fromisoformat(last_time_str).timestamp()
            elapsed = time.time() - last_ts
            dissipation = elapsed * COOLING_RATE
            current_heat = max(0.0, current_heat - dissipation)
        except ValueError:
            pass

    if not dna_list:
        # Still persist if heat changed (cooled down)
        if current_heat != heat_before_dissipation:
            state['system_heat'] = current_heat
            state['last_processed_timestamp'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            with open(ledger_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)

        log_structured(correlation_id, "end", "skipped", latency_ms=int((time.time()-start_time)*1000), actor_id=actor_id)
        print("[WARN] No DNA strings found in toSequence.txt")
        return

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
    error_occurred = False
    thermal_error_occurred = False
    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                log_structured(correlation_id, "parse", "skipped", actor_id=actor_id, idempotency_key=idempotency_key)
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            # Thermal Check
            if current_heat + HEAT_PER_SEQ > MAX_HEAT:
                print("Thermal Lockout! Wait for dissipation. The system is indifferent to your deadlines.")
                log_structured(correlation_id, "parse", "refused", actor_id=actor_id, idempotency_key=idempotency_key)
                thermal_error_occurred = True
                raise ThermalOverloadError("Heat Accumulation leading to lockout.")

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
                log_structured(correlation_id, "parse", "success", actor_id=actor_id, idempotency_key=idempotency_key)

            except RuleParseError as e:
                parsed_json.append({'dna': dna_str, 'error': str(e)})
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "error"
                log_structured(correlation_id, "parse", "error", actor_id=actor_id, idempotency_key=idempotency_key)

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            current_heat += HEAT_PER_SEQ
            new_processed_count += 1

    except ThermalOverloadError:
        pass
    except Exception as e:
        error_occurred = True
        log_structured(correlation_id, "parse", "error", actor_id=actor_id)
        raise e
    finally:
        # ATOMIC WRITE PATTERN:
        # We always persist if anything changed (new sequences processed OR heat dissipated)
        if new_processed_count > 0 or current_heat != heat_before_dissipation:
            state['system_heat'] = current_heat
            state['last_processed_timestamp'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            state['ledger'] = ledger

            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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

                    with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                        json.dump(state, lf, indent=2)
                        lf.flush()
                        os.fsync(lf.fileno())

                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)
                    os.replace(tmp_ledger, ledger_path)

                    log_structured(correlation_id, "persist", "success", actor_id=actor_id)
                except Exception as e:
                    log_structured(correlation_id, "persist", "error", actor_id=actor_id)
                    if not (error_occurred or thermal_error_occurred):
                        raise PersistenceError("Failed to write output files atomically") from e

        if thermal_error_occurred:
            log_structured(correlation_id, "end", "refused", latency_ms=int((time.time()-start_time)*1000), actor_id=actor_id)
            raise ThermalOverloadError("Batch interrupted due to heat.")

        if not error_occurred:
            log_structured(correlation_id, "end", "success", latency_ms=int((time.time()-start_time)*1000), actor_id=actor_id)

    if new_processed_count > 0:
        print(f"[OK] Processed {new_processed_count} new DNA strings. Heat: {current_heat:.1f}")
    else:
        print("[OK] No new DNA strings to process.")

if __name__ == '__main__':
    main()
