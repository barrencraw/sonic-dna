#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import datetime
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

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
    """Raised when system heat exceeds safety threshold."""
    pass

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# Thermal Fatigue Constants
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0  # units per second

# UI Message Keys
CONSEQUENCE_APPLIED = "Heat Accumulation"
REFUSAL_REASON = "Thermal Lockout"
NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

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

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    """
    Emits JSON logs with the JSON_LOG: prefix, including mandatory fields:
    timestamp (UTC), correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, and outcome_detail.
    """
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def load_ledger(ledger_path):
    """Loads the structured ledger. Handles backward compatibility for flat ledgers."""
    default_state = {
        "system_heat": 0.0,
        "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "ledger" in data:
                        return data
                    else:
                        # Legacy flat ledger convert
                        default_state['ledger'] = data
                        return default_state
        except Exception:
            return default_state
    return default_state

def save_ledger(ledger_path, state):
    """Atomically saves the ledger state."""
    folder = os.path.dirname(ledger_path)
    ensure_folder(folder)
    with tempfile.TemporaryDirectory(dir=folder) as tmp_dir:
        tmp_path = os.path.join(tmp_dir, 'ledger.json')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)

def run_batch(correlation_id=None):
    correlation_id = correlation_id or str(uuid.uuid4())
    actor_id = "system"

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

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

    state = load_ledger(ledger_path)
    ledger = state["ledger"]

    # Thermal Dissipation Calculation
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    last_time_str = state["last_processed_timestamp"]
    clean_last_time = last_time_str
    if clean_last_time.endswith('Z'):
        clean_last_time = clean_last_time[:-1] + '+00:00'
    try:
        last_time = datetime.datetime.fromisoformat(clean_last_time)
    except ValueError:
        last_time = now_utc

    elapsed = (now_utc - last_time).total_seconds()
    if elapsed < 0:
        elapsed = 0.0

    dissipation = elapsed * COOLING_RATE
    state["system_heat"] = max(0.0, state["system_heat"] - dissipation)

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        # Save ledger to record thermal dissipation during idle cycles
        try:
            state["last_processed_timestamp"] = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
            save_ledger(ledger_path, state)
        except Exception as e:
            raise PersistenceError(f"Failed to save ledger: {e}") from e
        return

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
    lockout_occurred = False

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            start_time = time.perf_counter()

            # Deduplication Check
            if idempotency_key in ledger:
                last_outcome = ledger[idempotency_key]['terminal_outcome']
                if last_outcome in ('success', 'error'):
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    log_structured(
                        correlation_id=correlation_id,
                        actor_id=actor_id,
                        chain_name="dna_batch_processing",
                        step="idempotency_check",
                        outcome=DNAStatus.SKIPPED.value,
                        latency_ms=latency_ms,
                        idempotency_key=idempotency_key,
                        outcome_detail=f"Deduplication hit. Already processed with outcome: {last_outcome}"
                    )
                    continue

            # Thermal Lockout Check
            if state["system_heat"] >= MAX_HEAT:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                # Mark as REFUSED in ledger
                ledger[idempotency_key] = {
                    'terminal_outcome': DNAStatus.REFUSED.value,
                    'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                }
                new_processed_count += 1
                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name="dna_batch_processing",
                    step="thermal_check",
                    outcome=DNAStatus.REFUSED.value,
                    latency_ms=latency_ms,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"{REFUSAL_REASON}: {CONSEQUENCE_APPLIED}. {NEXT_ACTION_HINT}"
                )
                lockout_occurred = True
                raise ThermalOverloadError(f"{REFUSAL_REASON}: {CONSEQUENCE_APPLIED}. {NEXT_ACTION_HINT}")

            # Process DNA Sequence
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
                outcome = DNAStatus.SUCCESS.value
                outcome_detail = "DNA successfully parsed"

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
                outcome_detail = str(e)

            state["system_heat"] += HEAT_PER_SEQ
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            new_processed_count += 1

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_processing",
                step="parse_dna",
                outcome=outcome,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail
            )

    except Exception as e:
        error_occurred = e

    finally:
        # Commit updated system heat and timestamp to ledger
        try:
            state["last_processed_timestamp"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            save_ledger(ledger_path, state)
        except Exception as e:
            if not error_occurred:
                error_occurred = PersistenceError(f"Failed to save ledger: {e}")

        # Rewrite output files only if new_processed_count > 0
        if new_processed_count > 0:
            try:
                with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                    tmp_json = os.path.join(tmp_dir, 'output.json')
                    tmp_csv = os.path.join(tmp_dir, 'output.csv')

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
                if not error_occurred:
                    error_occurred = PersistenceError(f"Failed to write output files atomically: {e}")

        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

        if error_occurred:
            raise error_occurred

# Alias main to run_batch for backward compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
