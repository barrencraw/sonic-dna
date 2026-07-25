#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# UI message keys for systemic feedback
SYSTEMIC_FEEDBACK = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

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

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when the compute hardware is overheated (system_heat >= 100.0)."""
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
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    ledger_dir = os.path.dirname(ledger_path)
    with tempfile.NamedTemporaryFile('w', dir=ledger_dir, delete=False, encoding='utf-8') as tf:
        temp_name = tf.name
        try:
            json.dump(ledger, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        except Exception as e:
            tf.close()
            if os.path.exists(temp_name):
                os.remove(temp_name)
            raise e
    os.replace(temp_name, ledger_path)

def log_structured(correlation_id=None, actor_id="orchestrator", chain_name="dna_batch_parsing", step="process_sequence", outcome="success", latency_ms=0, idempotency_key=None, outcome_detail=None):
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None):
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    # Output paths defined once at the beginning of run_batch() to prevent UnboundLocalError
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

    raw_ledger = load_ledger(ledger_path)
    if isinstance(raw_ledger, dict) and "ledger" in raw_ledger:
        ledger_data = raw_ledger["ledger"]
        system_heat = raw_ledger.get("system_heat", 0.0)
        last_processed_time = raw_ledger.get("last_processed_time", None)
    else:
        ledger_data = raw_ledger
        system_heat = 0.0
        last_processed_time = None

    current_time = datetime.datetime.now(datetime.timezone.utc)
    current_time_str = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Calculate heat dissipation
    system_heat_changed = False
    if last_processed_time:
        try:
            last_time = datetime.datetime.fromisoformat(last_processed_time)
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=datetime.timezone.utc)
            elapsed = (current_time - last_time).total_seconds()
            if elapsed > 0:
                dissipation_rate = 1.0
                new_heat = max(0.0, system_heat - (elapsed * dissipation_rate))
                if new_heat != system_heat:
                    system_heat = new_heat
                    system_heat_changed = True
        except Exception:
            pass

    # 1) Load existing JSON output
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
    error_occurred = None

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger_data:
                term_outcome = ledger_data[idempotency_key].get('terminal_outcome', '')
                if term_outcome.startswith('success') or term_outcome.startswith('error'):
                    print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
                    continue

            # Check thermal lockout before processing
            if system_heat >= 100.0:
                # Standardized JSON log for thermal lockout refusal
                log_structured(
                    correlation_id=correlation_id,
                    step="thermal_lockout_check",
                    outcome=DNAStatus.REFUSED,
                    idempotency_key=idempotency_key,
                    outcome_detail=SYSTEMIC_FEEDBACK["refusal_reason"]
                )
                raise ThermalOverloadError(f"{SYSTEMIC_FEEDBACK['refusal_reason']}. {SYSTEMIC_FEEDBACK['next_action_hint']}")

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
            start_time = time.time()

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
                outcome = DNAStatus.SUCCESS
                outcome_detail = "Successfully parsed DNA sequence"

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
                outcome_detail = f"Parse error: {str(e)}"

            latency_ms = int((time.time() - start_time) * 1000)

            # Standardized logging
            log_structured(
                correlation_id=correlation_id,
                step="process_sequence",
                outcome=outcome,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail
            )

            # Store outcome inside ledger_data
            ledger_data[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': current_time_str
            }
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")

            # Accumulate system heat and log the consequence
            system_heat += 15.0
            log_structured(
                correlation_id=correlation_id,
                step="apply_thermal_consequence",
                outcome=DNAStatus.SUCCESS,
                idempotency_key=idempotency_key,
                outcome_detail=f"{SYSTEMIC_FEEDBACK['consequence_applied']} applied. New heat: {system_heat:.2f}"
            )

            new_processed_count += 1

    except Exception as e:
        error_occurred = e
        raise

    finally:
        try:
            # Save ledger atomically if heat state or processed count changed
            if new_processed_count > 0 or system_heat_changed:
                raw_ledger = {
                    "ledger": ledger_data,
                    "system_heat": system_heat,
                    "last_processed_time": current_time_str
                }
                save_ledger(ledger_path, raw_ledger)

            # Save JSON and CSV atomically if new sequences processed
            if new_processed_count > 0:
                with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                    tmp_json = os.path.join(tmp_dir, 'output.json')
                    tmp_csv = os.path.join(tmp_dir, 'output.csv')

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

                print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger_data)}")
                print(f"     JSON → {json_output_path}")
                print(f"     CSV  → {csv_output_path}")

        except Exception as cleanup_err:
            if error_occurred is None:
                raise PersistenceError("Failed to write output files atomically") from cleanup_err
            else:
                print(f"[Cleanup Error] Persistence failed during error recovery: {cleanup_err}")

main = run_batch

if __name__ == '__main__':
    main()
