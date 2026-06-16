#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    PROCESSING = "processing"

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

# Thermal Constants
MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE_PER_SEC = 0.01

MSG_CONSEQUENCE = "System heat is rising. Efficiency may decrease."
MSG_REFUSAL = "MAX_HEAT reached. Safety lockout engaged. Batch refused."
MSG_HINT = "Wait for the system to cool down before submitting more DNA."

def log_structured(step, outcome, correlation_id, start_time=None, extra=None):
    now = time.time()
    latency = int((now - start_time) * 1000) if start_time else None
    log_data = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now)),
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_processing",
        "step": step,
        "outcome": outcome,
        "actor_id": "jules_agent"
    }
    if latency is not None:
        log_data["latency_ms"] = latency
    if extra:
        log_data.update(extra)
    print(f"JSON_LOG: {json.dumps(log_data)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

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

def load_ledger(ledger_path):
    # Migration logic: check if old ledger exists
    old_ledger_path = ledger_path.replace('ledger.json', 'processed_ledger.json')

    state = {
        "system_heat": 0.0,
        "last_processed_timestamp": 0.0,
        "ledger": {}
    }

    actual_path = ledger_path
    if not os.path.exists(ledger_path) and os.path.exists(old_ledger_path):
        # Migrate old ledger
        try:
            with open(old_ledger_path, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                state["ledger"] = old_data
        except Exception:
            pass
    elif os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "ledger" in data:
                    state = data
                else:
                    # Legacy format but named ledger.json
                    state["ledger"] = data
        except Exception:
            pass
    return state

def save_state_atomic(ledger_path, state, json_path, json_data, csv_path, csv_rows, fieldnames):
    """
    Atomic write for ledger, json output, and csv output.
    """
    data_dir = os.path.dirname(ledger_path)
    output_dir = os.path.dirname(json_path)

    # We use a temp dir in data/ to ensure same filesystem for ledger and outputs if possible,
    # but they might be in different subdirs. Let's use a temp dir in each parent.

    def atomic_write_json(target_path, content):
        parent = os.path.dirname(target_path)
        with tempfile.NamedTemporaryFile('w', dir=parent, delete=False, encoding='utf-8', suffix='.tmp') as tf:
            json.dump(content, tf, indent=2)
            temp_name = tf.name
        os.replace(temp_name, target_path)

    def atomic_write_csv(target_path, rows, fields):
        parent = os.path.dirname(target_path)
        with tempfile.NamedTemporaryFile('w', dir=parent, delete=False, encoding='utf-8', suffix='.tmp', newline='') as tf:
            writer = csv.DictWriter(tf, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                out = {k: row.get(k, '') for k in fields}
                writer.writerow(out)
            temp_name = tf.name
        os.replace(temp_name, target_path)

    try:
        atomic_write_json(ledger_path, state)
        atomic_write_json(json_path, json_data)
        atomic_write_csv(csv_path, csv_rows, fieldnames)
    except Exception as e:
        raise PersistenceError(f"Atomic write failed: {e}") from e

def main(correlation_id=None):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    start_time = time.time()
    log_structured("batch_start", "processing", correlation_id, start_time)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured("rule_load", "error", correlation_id, start_time, {"error": str(e)})
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured("input_read", "error", correlation_id, start_time, {"error": str(e)})
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured("batch_end", "skipped", correlation_id, start_time, {"reason": "no_input"})
        return

    full_state = load_ledger(ledger_path)
    ledger = full_state["ledger"]

    # Update heat based on cooling
    now = time.time()
    elapsed = now - full_state.get("last_processed_timestamp", now)
    cooling = elapsed * COOLING_RATE_PER_SEC
    current_heat = max(0.0, full_state.get("system_heat", 0.0) - cooling)

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                # Migration: rename 'dna' to 'dna_sequence'
                for entry in parsed_json:
                    if 'dna' in entry:
                        entry['dna_sequence'] = entry.pop('dna')
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
                    # Migration: rename 'dna' to 'dna_sequence'
                    fieldnames = [f if f != 'dna' else 'dna_sequence' for f in reader.fieldnames]
                    all_flattened_keys = set(fieldnames)
                    for row in reader:
                        if 'dna' in row:
                            row['dna_sequence'] = row.pop('dna')
                        csv_rows.append(row)
        except Exception:
            pass

    new_processed_count = 0

    try:
        for dna_seq in dna_list:
            outcome = DNAStatus.PROCESSING.value
            idempotency_key = dna_seq

            if idempotency_key in ledger:
                outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS.value)
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={outcome}")
                log_structured("item_process", DNAStatus.SKIPPED.value, correlation_id, start_time, {"dna_sequence": dna_seq})
                continue

            # Check heat
            if current_heat + HEAT_PER_ITEM > MAX_HEAT:
                print(f"[THERMAL] {MSG_REFUSAL} Current heat: {current_heat:.2f}")
                log_structured("item_process", "refused", correlation_id, start_time, {"reason": "thermal_overload", "heat": current_heat})
                raise ThermalOverloadError(MSG_REFUSAL)

            current_heat += HEAT_PER_ITEM
            if current_heat > MAX_HEAT * 0.7:
                print(f"[THERMAL] {MSG_CONSEQUENCE} Heat: {current_heat:.2f}")

            try:
                result = calculator.parse(dna_seq)
                entry = {
                    'dna_sequence': dna_seq,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna_sequence'] = dna_seq
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.SUCCESS.value

            except RuleParseError as e:
                entry = {
                    'dna_sequence': dna_seq,
                    'error': str(e)
                }
                parsed_json.append(entry)
                flat = {'dna_sequence': dna_seq, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR.value
                log_structured("item_process", outcome, correlation_id, start_time, {"dna_sequence": dna_seq, "error": str(e)})
            else:
                log_structured("item_process", outcome, correlation_id, start_time, {"dna_sequence": dna_seq})

            # Update ledger per item
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1

            # Atomic save after each item (as per loop-based update requirement)
            full_state["system_heat"] = current_heat
            full_state["last_processed_timestamp"] = time.time()
            full_state["ledger"] = ledger

            save_state_atomic(ledger_path, full_state, json_output_path, parsed_json, csv_output_path, csv_rows, sorted(all_flattened_keys))

    except ThermalOverloadError:
        print(f"[HINT] {MSG_HINT}")
    except Exception as e:
        log_structured("batch_process", "error", correlation_id, start_time, {"error": str(e)})
        raise
    finally:
        # Final save to ensure heat/timestamp is updated even if no items were processed
        full_state["system_heat"] = current_heat
        full_state["last_processed_timestamp"] = time.time()
        full_state["ledger"] = ledger
        save_state_atomic(ledger_path, full_state, json_output_path, parsed_json, csv_output_path, csv_rows, sorted(all_flattened_keys))
        log_structured("batch_end", DNAStatus.SUCCESS.value if new_processed_count > 0 else DNAStatus.SKIPPED.value, correlation_id, start_time, {"processed_count": new_processed_count, "final_heat": current_heat})

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
