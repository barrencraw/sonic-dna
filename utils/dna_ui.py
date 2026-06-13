#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Constants ---
MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE_PER_SEC = 0.01

MSG_CONSEQUENCE = "System showing signs of thermal drift. Output accuracy may degrade."
MSG_REFUSAL = "Hardware safety lockout: Thermal threshold exceeded. Cooling required."
MSG_HINT = "System is indifferent. Cooling occurs when idle."

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    DEDUPE_SKIP = "dedupe_skip"
    THERMAL_SKIP = "thermal_skip"
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
    """Raised when system is too hot to process DNA."""
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
    if not os.path.isfile(input_path):
        return dna_list
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

def log_structured(step, outcome, correlation_id=None, dna_sequence=None, latency_ms=None, start_time=None, actor_id="system"):
    if start_time and latency_ms is None:
        latency_ms = int((time.time() - start_time) * 1000)

    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome,
        "actor_id": actor_id
    }
    if dna_sequence:
        log_entry["idempotency_key"] = dna_sequence
    if latency_ms is not None:
        log_entry["latency_ms"] = latency_ms

    print(f"JSON_LOG: {json.dumps(log_entry)}")

def apply_cooling(state):
    last_ts = state.get("last_processed_timestamp")
    current_heat = state.get("system_heat", 0.0)

    if last_ts:
        elapsed = time.time() - last_ts
        cooling = elapsed * COOLING_RATE_PER_SEC
        new_heat = max(0.0, current_heat - cooling)
        state["system_heat"] = new_heat
    else:
        state["system_heat"] = current_heat
    return state

def load_ledger(ledger_path):
    if not os.path.exists(ledger_path):
        return {"system_heat": 0.0, "last_processed_timestamp": None, "ledger": {}}

    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Migration: if it's a legacy flat dict, wrap it
            if "ledger" not in data:
                return {
                    "system_heat": 0.0,
                    "last_processed_timestamp": None,
                    "ledger": data
                }
            return data
    except Exception:
        return {"system_heat": 0.0, "last_processed_timestamp": None, "ledger": {}}

def save_ledger_atomic(ledger_path, state):
    temp_dir = os.path.dirname(ledger_path)
    with tempfile.NamedTemporaryFile('w', dir=temp_dir, delete=False, encoding='utf-8') as tf:
        json.dump(state, tf, indent=2)
        temp_name = tf.name
    os.replace(temp_name, ledger_path)

def main(correlation_id=None, base_dir=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    if base_dir is None:
        base_dir = os.getcwd()

    raw_folder = os.path.join(base_dir, 'data', 'raw')
    output_folder = os.path.join(base_dir, 'data', 'output')
    legacy_ledger_path = os.path.join(base_dir, 'data', 'processed_ledger.json')
    ledger_path = os.path.join(base_dir, 'data', 'ledger.json')

    ensure_folder(output_folder)

    # Legacy migration
    if os.path.exists(legacy_ledger_path) and not os.path.exists(ledger_path):
        os.rename(legacy_ledger_path, ledger_path)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    state = load_ledger(ledger_path)
    state = apply_cooling(state)
    old_heat = state["system_heat"]

    dna_list = read_input_file(input_file)
    if not dna_list:
        # Still apply cooling even if no DNA
        if state["system_heat"] != old_heat:
            state["last_processed_timestamp"] = time.time()
            save_ledger_atomic(ledger_path, state)
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(base_dir, 'rules'))
    except Exception as e:
        log_structured("load_rules", "error", correlation_id=correlation_id, actor_id="system")
        raise RuleLoadError(f"Could not load rules") from e

    # Load existing outputs for cumulative append
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as f:
                parsed_json = json.load(f)
                # Field migration
                for item in parsed_json:
                    if 'dna' in item:
                        item['dna_sequence'] = item.pop('dna')
        except Exception:
            pass

    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                if fieldnames:
                    # Field migration in headers
                    new_fieldnames = []
                    for fn in fieldnames:
                        if fn == 'dna':
                            new_fieldnames.append('dna_sequence')
                        else:
                            new_fieldnames.append(fn)
                    all_flattened_keys = set(new_fieldnames)
                    for row in reader:
                        if 'dna' in row:
                            row['dna_sequence'] = row.pop('dna')
                        csv_rows.append(row)
        except Exception:
            pass

    new_processed_count = 0
    results_to_ledger = [] # (dna, outcome)
    processed_in_batch = set()

    try:
        for dna_sequence in dna_list:
            if dna_sequence in processed_in_batch:
                continue
            processed_in_batch.add(dna_sequence)
            step_start = time.time()
            if dna_sequence in state["ledger"]:
                log_structured("deduplication", DNAStatus.DEDUPE_SKIP.value,
                               correlation_id=correlation_id, dna_sequence=dna_sequence)
                continue

            # Thermal check
            if state["system_heat"] + HEAT_PER_ITEM > MAX_HEAT:
                log_structured("thermal_check", DNAStatus.THERMAL_SKIP.value,
                               correlation_id=correlation_id, dna_sequence=dna_sequence)
                print(f"[WARN] {MSG_REFUSAL}")
                raise ThermalOverloadError(MSG_REFUSAL)

            state["system_heat"] += HEAT_PER_ITEM

            try:
                result = calculator.parse(dna_sequence)
                entry = {
                    'dna_sequence': dna_sequence,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna_sequence'] = dna_sequence
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                outcome = DNAStatus.SUCCESS.value
                log_structured("parse", outcome, correlation_id=correlation_id,
                               dna_sequence=dna_sequence, start_time=step_start)

            except RuleParseError as e:
                outcome = f"{DNAStatus.ERROR.value}: {str(e)}"
                parsed_json.append({'dna_sequence': dna_sequence, 'error': str(e)})
                flat = {'dna_sequence': dna_sequence, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                log_structured("parse", DNAStatus.ERROR.value, correlation_id=correlation_id,
                               dna_sequence=dna_sequence, start_time=step_start)

            results_to_ledger.append((dna_sequence, outcome))
            new_processed_count += 1

            if state["system_heat"] > 7.0:
                print(f"[HINT] {MSG_CONSEQUENCE}")

    finally:
        # Atomic commit of outputs and state
        if new_processed_count > 0 or state["system_heat"] != old_heat:
            state["last_processed_timestamp"] = time.time()

            # Update ledger with results from this session
            for d_seq, out in results_to_ledger:
                state["ledger"][d_seq] = {
                    "terminal_outcome": out,
                    "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
                }

            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

                try:
                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    fieldnames = sorted(all_flattened_keys)
                    if 'dna_sequence' in fieldnames:
                        fieldnames.remove('dna_sequence')
                        fieldnames = ['dna_sequence'] + fieldnames

                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out_row = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out_row)
                        cf.flush()
                        os.fsync(cf.fileno())

                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)
                    save_ledger_atomic(ledger_path, state)

                except Exception as e:
                    log_structured("persistence", "error", correlation_id=correlation_id)
                    raise PersistenceError("Atomic write failed") from e

    print(f"[OK] Processed {new_processed_count} new items. Heat: {state['system_heat']:.2f}/10.0")

if __name__ == '__main__':
    main()
