#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
import uuid
from utils.dna_calculator import DNACalculator, RuleParseError

# Standard limits and rates for the Thermal Fatigue system
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0

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
    """Raised when system is in a lockout state due to hardware thermal fatigue."""
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
    """
    Loads ledger and returns structured ledger dictionary with:
    {
      "system_heat": float,
      "last_update": "ISO 8601 UTC timestamp",
      "ledger": { dna: { "terminal_outcome": str, "timestamp": str } }
    }
    Automatically converts flat ledger to structured ledger.
    """
    default_ledger = {
        "system_heat": 0.0,
        "last_update": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "ledger" in data:
                        # Structured ledger
                        if "system_heat" not in data:
                            data["system_heat"] = 0.0
                        if "last_update" not in data:
                            data["last_update"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                        return data
                    else:
                        # Migrate flat ledger to structured ledger
                        system_heat = data.pop("system_heat", 0.0)
                        last_update = data.pop("last_update", datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
                        return {
                            "system_heat": system_heat,
                            "last_update": last_update,
                            "ledger": data
                        }
        except Exception:
            pass
    return default_ledger

def save_ledger(ledger_path, ledger_data):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger_data, f, indent=2)

def log_structured(step, outcome, latency_ms=0, correlation_id=None, actor_id="system", chain_name="dna_batch_parser", idempotency_key=None, outcome_detail=None):
    """
    Structured logger with 'JSON_LOG:' prefix. All values are logged in JSON format.
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None):
    correlation_id = correlation_id or str(uuid.uuid4())
    start_time = time.time()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured("initialize", "error", correlation_id=correlation_id, outcome_detail="Input file not found")
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured("load_rules", "error", correlation_id=correlation_id, outcome_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured("read_input", "error", correlation_id=correlation_id, outcome_detail=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured("read_input", "warning", correlation_id=correlation_id, outcome_detail="No DNA strings found")
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    # 1) Load the structured ledger
    state = load_ledger(ledger_path)
    system_heat = state["system_heat"]
    last_update_str = state["last_update"]
    ledger = state["ledger"]

    # Calculate thermal fatigue cooling (heat dissipation) since last update
    try:
        last_update = datetime.datetime.fromisoformat(last_update_str.replace('Z', '+00:00'))
    except Exception:
        last_update = datetime.datetime.now(datetime.timezone.utc)

    current_time = datetime.datetime.now(datetime.timezone.utc)
    elapsed_seconds = max(0.0, (current_time - last_update).total_seconds())
    cooling_amount = elapsed_seconds * COOLING_RATE
    system_heat = max(0.0, system_heat - cooling_amount)

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
    error_occurred = None

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                log_structured("process_sequence", "skipped", correlation_id=correlation_id, idempotency_key=idempotency_key, outcome_detail="Deduplication hit")
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            # Check for thermal fatigue lockout (refusal reason)
            if system_heat >= MAX_HEAT:
                log_structured(
                    step="process_sequence",
                    outcome="refused",
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    outcome_detail="Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines."
                )
                raise ThermalOverloadError(
                    "Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines."
                )

            # Process newly added sequence
            outcome = "success"
            parse_start = time.time()
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
                outcome_detail = "Successfully parsed sequence"

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
                outcome = "error"
                outcome_detail = str(e)

            # Apply thermal fatigue consequence
            system_heat = min(MAX_HEAT, system_heat + HEAT_PER_SEQ)

            # Record in ledger immediately
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            new_processed_count += 1

            latency_ms = int((time.time() - parse_start) * 1000)
            log_structured(
                step="process_sequence",
                outcome=outcome,
                latency_ms=latency_ms,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail
            )

    except Exception as e:
        error_occurred = e

    finally:
        # Save ledger and updated system heat
        state["system_heat"] = system_heat
        state["last_update"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        state["ledger"] = ledger

        # ATOMIC WRITE PATTERN:
        # Write to temporary files first, then replace them atomically
        try:
            # We always write the ledger, even if 0 new sequences were processed,
            # so that the updated system heat / cooling cycles are saved!
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

                # 1) Write ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(state, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # Only rewrite JSON and CSV output files if new sequences were actually processed
                # or if the file does not exist.
                if new_processed_count > 0 or not os.path.exists(json_output_path) or not os.path.exists(csv_output_path):
                    # 2) Write JSON output to temp
                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    # 3) Write CSV output to temp
                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())

                # Atomic renames
                os.replace(tmp_ledger, ledger_path)
                if new_processed_count > 0 or not os.path.exists(json_output_path) or not os.path.exists(csv_output_path):
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

        except Exception as e:
            # If a persistence error occurs during cleanup, only raise if no previous error was detected
            if error_occurred is None:
                raise PersistenceError("Failed to write output files atomically") from e
            else:
                print(f"[CRITICAL] Persistence failed during error cleanup: {e}")

        # Propagate the original error if one occurred
        if error_occurred:
            raise error_occurred

    total_latency_ms = int((time.time() - start_time) * 1000)
    log_structured(
        step="run_batch",
        outcome="success" if new_processed_count > 0 else "skipped",
        latency_ms=total_latency_ms,
        correlation_id=correlation_id,
        outcome_detail=f"Processed {new_processed_count} new DNA strings."
    )
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

def main():
    run_batch()

if __name__ == '__main__':
    main()
