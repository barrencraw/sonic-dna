#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from datetime import datetime
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Constants & Messaging ---
MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE_PER_SEC = 0.01  # Example rate
MSG_CONSEQUENCE = "thermal drift/degradation detected"
MSG_REFUSAL = "hardware safety lockout: thermal limit reached"
MSG_HINT = "indifferent cooling hint: wait for system to dissipate energy"

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

def log_structured(step, correlation_id, outcome=None, dna_sequence=None, latency_ms=None, error=None, extra=None):
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_chain",
        "step": step,
        "actor_id": "system"
    }
    if outcome: log_entry["outcome"] = outcome
    if dna_sequence: log_entry["dna_sequence"] = dna_sequence
    if latency_ms is not None: log_entry["latency_ms"] = latency_ms
    if error: log_entry["error"] = error
    if extra: log_entry.update(extra)

    print(f"JSON_LOG: {json.dumps(log_entry)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_list = []
    if not os.path.exists(input_path):
        return dna_list
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

def flatten_parsed(rule_name, values_dict, parent_key=''):
    items = {}
    for k, v in values_dict.items():
        new_key = f"{parent_key}.{k}" if parent_key else f"{rule_name}.{k}"
        if isinstance(v, dict):
            items.update(flatten_parsed(rule_name, v, new_key))
        else:
            items[new_key] = v
    return items

def apply_cooling(state):
    current_time = time.time()
    last_time = state.get("last_processed_timestamp", current_time)
    current_heat = state.get("system_heat", 0.0)

    elapsed = current_time - last_time
    reduction = elapsed * COOLING_RATE_PER_SEC
    new_heat = max(0.0, current_heat - reduction)

    state["system_heat"] = new_heat
    state["last_processed_timestamp"] = current_time
    return new_heat

def load_ledger(ledger_path):
    # Migration handling
    legacy_path = ledger_path.replace("ledger.json", "processed_ledger.json")
    if os.path.exists(legacy_path) and not os.path.exists(ledger_path):
        os.rename(legacy_path, ledger_path)

    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Check if it's legacy flat dict
                if "ledger" not in data:
                    return {
                        "system_heat": 0.0,
                        "last_processed_timestamp": time.time(),
                        "ledger": data
                    }
                return data
        except Exception:
            pass
    return {
        "system_heat": 0.0,
        "last_processed_timestamp": time.time(),
        "ledger": {}
    }

def main(base_dir=None, correlation_id=None):
    if base_dir is None:
        base_dir = os.getcwd()
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    raw_folder = os.path.join(base_dir, 'data', 'raw')
    output_folder = os.path.join(base_dir, 'data', 'output')
    ledger_path = os.path.join(base_dir, 'data', 'ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # 1) Load state
    state = load_ledger(ledger_path)
    old_heat = state["system_heat"]
    apply_cooling(state)

    # Instantiate calculator
    rules_folder = os.path.join(base_dir, 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        log_structured("init", correlation_id, outcome="error", error=f"RuleLoadError: {str(e)}")
        raise RuleLoadError(f"Could not load rules from {rules_folder}") from e

    # Read DNA strings
    dna_list = read_input_file(input_file)
    if not dna_list:
        # Still might need to save cooled state
        if state["system_heat"] != old_heat:
            with open(ledger_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        return

    # Load existing outputs for appending (simulated here as reading and merging)
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as f:
                parsed_json = json.load(f)
                # Field migration: dna -> dna_sequence
                for entry in parsed_json:
                    if 'dna' in entry:
                        entry['dna_sequence'] = entry.pop('dna')
        except Exception: pass

    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                if fieldnames:
                    # Field migration: dna -> dna_sequence
                    new_fieldnames = [fn if fn != 'dna' else 'dna_sequence' for fn in fieldnames]
                    all_flattened_keys = set(new_fieldnames)
                    for row in reader:
                        if 'dna' in row:
                            row['dna_sequence'] = row.pop('dna')
                        csv_rows.append(row)
        except Exception: pass

    new_processed_count = 0
    results_to_ledger = []
    processed_in_batch = set()

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in state["ledger"] or idempotency_key in processed_in_batch:
                outcome = state["ledger"].get(idempotency_key, {}).get("terminal_outcome", "success")
                log_structured("process_item", correlation_id, outcome="skipped", dna_sequence=dna_str, extra={"reason": "idempotency_hit", "previous_outcome": outcome})
                continue

            # Pre-parse heat check
            if state["system_heat"] + HEAT_PER_ITEM > MAX_HEAT:
                log_structured("process_item", correlation_id, outcome="refusal", dna_sequence=dna_str, error=MSG_REFUSAL, extra={"system_heat": state["system_heat"]})
                print(f"[WARN] {MSG_REFUSAL}. {MSG_HINT}")
                raise ThermalOverloadError(MSG_REFUSAL)

            start_time = time.time()
            error_detail = None
            try:
                result = calculator.parse(dna_str)
                entry = {
                    'dna_sequence': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna_sequence'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"
                state["system_heat"] += HEAT_PER_ITEM
            except RuleParseError as e:
                error_detail = str(e)
                parsed_json.append({'dna_sequence': dna_str, 'error': error_detail})
                flat = {'dna_sequence': dna_str, 'error': error_detail}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "error"

            latency_ms = int((time.time() - start_time) * 1000)
            log_structured("process_item", correlation_id, outcome=outcome, dna_sequence=dna_str, latency_ms=latency_ms, error=error_detail)

            results_to_ledger.append((idempotency_key, outcome))
            processed_in_batch.add(idempotency_key)
            new_processed_count += 1

    except ThermalOverloadError:
        # We break the loop but still want to save what we did
        pass
    finally:
        # Atomic Write Block
        if new_processed_count > 0 or state["system_heat"] != old_heat:
            # Update ledger entries before saving
            for key, outcome in results_to_ledger:
                state["ledger"][key] = {
                    "terminal_outcome": outcome,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }

            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

                try:
                    # Write JSON
                    with open(tmp_json, 'w', encoding='utf-8') as f:
                        json.dump(parsed_json, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())

                    # Write CSV
                    fieldnames = sorted(all_flattened_keys)
                    if 'dna_sequence' in fieldnames:
                        fieldnames.remove('dna_sequence')
                        fieldnames = ['dna_sequence'] + fieldnames

                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            writer.writerow({k: row.get(k, '') for k in fieldnames})
                        f.flush()
                        os.fsync(f.fileno())

                    # Write Ledger
                    with open(tmp_ledger, 'w', encoding='utf-8') as f:
                        json.dump(state, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())

                    # Atomic renames
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)
                    os.replace(tmp_ledger, ledger_path)

                    log_structured("batch_commit", correlation_id, outcome="success", extra={"new_items": new_processed_count, "system_heat": state["system_heat"]})
                except Exception as e:
                    log_structured("batch_commit", correlation_id, outcome="error", error=str(e))
                    raise PersistenceError(f"Failed to write output files atomically: {e}") from e

    if new_processed_count > 0:
        print(f"[OK] Processed {new_processed_count} new DNA strings.")

if __name__ == '__main__':
    main()
