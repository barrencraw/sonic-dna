#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

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

class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when processing is blocked due to safety lockout threshold."""
    pass

def load_ledger(ledger_path):
    """
    Loads the ledger. Supports both legacy flat dictionary format and new structured format.
    Returns a dict with 'system_heat', 'last_processed_time', and 'ledger' (the flat ledger dict).
    """
    default_structure = {
        "system_heat": 0.0,
        "last_processed_time": None,
        "ledger": {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "ledger" in data and "system_heat" in data:
                        return data
                    else:
                        # Legacy flat ledger format
                        return {
                            "system_heat": 0.0,
                            "last_processed_time": None,
                            "ledger": data
                        }
        except Exception:
            pass
    return default_structure

def save_ledger(ledger_path, ledger_data):
    """
    Saves the ledger data atomically using a temporary file write, flush, fsync, and replace sequence.
    Handles save exceptions gracefully, cleaning up any partially written temporary file before
    re-raising a typed LedgerSaveError.
    """
    dir_name = os.path.dirname(ledger_path)
    if not dir_name:
        dir_name = "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix="ledger_", suffix=".json")
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        # Cleanup temporary file if it still exists
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically to {ledger_path}") from e

def log_structured(correlation_id, step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None, actor_id="mainframe"):
    """
    Emits JSON logs with the 'JSON_LOG:' prefix.
    Mandatory fields: timestamp (UTC), correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, and outcome_detail.
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": "dna_batch_parser",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or "N/A"
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None):
    start_time = time.time()
    # Define standardized message keys for convenience:
    # consequence_applied: "Heat Accumulation"
    # refusal_reason: "Thermal Lockout"
    # next_action_hint: "Wait for dissipation. The system is indifferent to your deadlines."

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
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        print("[WARN] No DNA strings found in toSequence.txt")

    # Load ledger structure (contains system_heat, last_processed_time, ledger)
    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data.get("ledger", {})
    system_heat = ledger_data.get("system_heat", 0.0)
    last_processed_time_str = ledger_data.get("last_processed_time")

    # 1) Calculate thermal dissipation (cooling)
    current_time = datetime.datetime.now(datetime.timezone.utc)
    if last_processed_time_str:
        try:
            last_time = datetime.datetime.strptime(last_processed_time_str, '%Y-%m-%dT%H:%M:%SZ')
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = (current_time - last_time).total_seconds()
            elapsed_seconds = max(0.0, elapsed_seconds)
        except Exception:
            elapsed_seconds = 0.0
    else:
        elapsed_seconds = 0.0

    dissipated_heat = elapsed_seconds * 0.5
    system_heat = max(0.0, system_heat - dissipated_heat)

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
    error_occurred = False

    # Pre-scan the input list for non-deduplicated items to see if we actually have processing to do
    new_items_to_process = [seq for seq in dna_sequence_list if seq not in ledger]

    try:
        # Check initial thermal lockout
        if new_items_to_process and system_heat >= 10.0:
            log_structured(
                correlation_id=correlation_id,
                step="thermal_check",
                outcome="refused",
                idempotency_key="batch",
                outcome_detail="Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines."
            )
            raise ThermalOverloadError("Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines.")

        for dna_sequence in dna_sequence_list:
            idempotency_key = dna_sequence
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            # Check lockout during processing
            if system_heat >= 10.0:
                log_structured(
                    correlation_id=correlation_id,
                    step="thermal_check_in_loop",
                    outcome="refused",
                    idempotency_key=idempotency_key,
                    outcome_detail="Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines."
                )
                raise ThermalOverloadError("Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines.")

            # Processing sequence
            try:
                result = calculator.parse(dna_sequence)
                entry = {
                    'dna': dna_sequence,
                    'dna_sequence': dna_sequence,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_sequence
                flat['dna_sequence'] = dna_sequence
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_sequence,
                    'dna_sequence': dna_sequence,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = f"error: {str(e)}"

            # Heat accumulation per processed sequence
            system_heat += 2.0
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
            log_structured(
                correlation_id=correlation_id,
                step="parse_sequence",
                outcome=outcome,
                idempotency_key=idempotency_key,
                outcome_detail=f"Heat Accumulation: system_heat={system_heat:.2f}"
            )
            new_processed_count += 1

            # Check if this addition triggers a lockout
            if system_heat >= 10.0:
                log_structured(
                    correlation_id=correlation_id,
                    step="thermal_threshold_check",
                    outcome="overload",
                    idempotency_key=idempotency_key,
                    outcome_detail="Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines."
                )
                raise ThermalOverloadError("Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines.")

    except Exception as e:
        error_occurred = True
        raise

    finally:
        # ATOMIC WRITE PATTERN:
        # 1. Write JSON/CSV outputs to temp and rename only if new_processed_count > 0
        try:
            if new_processed_count > 0:
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

                    except Exception as persist_err:
                        raise PersistenceError("Failed to write output files atomically") from persist_err

            # Update the ledger data with system heat, current timestamp, and the ledger dictionary
            ledger_data["system_heat"] = system_heat
            ledger_data["last_processed_time"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            ledger_data["ledger"] = ledger

            # Always save ledger (this records thermal dissipation/updates even if 0 new items processed)
            save_ledger(ledger_path, ledger_data)

        except Exception as cleanup_err:
            if not error_occurred:
                raise cleanup_err

    # Print summary
    latency_ms = int((time.time() - start_time) * 1000)
    print(f"[OK] Parsed {len(dna_sequence_list)} DNA strings.")
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}. System heat: {system_heat:.2f}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")
    log_structured(
        correlation_id=correlation_id,
        step="run_batch_complete",
        outcome="success",
        latency_ms=latency_ms,
        outcome_detail=f"Processed={new_processed_count} total_ledger={len(ledger)} heat={system_heat:.2f}"
    )

main = run_batch

if __name__ == '__main__':
    main()
