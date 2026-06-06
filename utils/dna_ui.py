#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
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

import tempfile
import shutil

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
    """Raised when system heat exceeds maximum safety limits."""
    pass

# Thermal Constants
MAX_HEAT = 10.0
NOISE_THRESHOLD = 7.0
COOLING_RATE = 0.0083 # ~1 unit every 2 mins

# UI Message Keys (Indifferent Tone)
MSG_CONSEQUENCE = "THERMAL DRIFT: {heat:.2f} - Signal degradation imminent."
MSG_REFUSAL = "HARDWARE REFUSAL: Thermal threshold exceeded. Cooling required."
MSG_HINT = "The fans are spinning at maximum. It doesn't care about your deadlines."

def apply_cooling(state):
    """Calculates and applies passive cooling since the last run."""
    now = time.time()
    last = state.get("last_processed_timestamp", now)
    elapsed = now - last

    reduction = elapsed * COOLING_RATE
    old_heat = state["system_heat"]
    state["system_heat"] = max(0.0, old_heat - reduction)
    state["last_processed_timestamp"] = now
    return old_heat, state["system_heat"]

def calculate_heat_delta(result):
    """
    Calculates the thermal impact of processing a DNA sequence.
    VOL (Volume) rules generate more heat.
    """
    base_gain = 0.1
    if result.get('rule') == 'Volume':
        return base_gain + 0.2
    return base_gain
def load_ledger(ledger_path):
    """
    Loads the ledger from disk. Supports migration from legacy flat-dict
    to the new state-dictionary structure.
    """
    default_state = {
        "system_heat": 0.0,
        "last_processed_timestamp": 0.0,
        "ledger": {}
    }
    if not os.path.exists(ledger_path):
        return default_state

    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Migration: if 'ledger' key is missing, treat the whole dict as the ledger
            if "ledger" not in data:
                return {
                    "system_heat": 0.0,
                    "last_processed_timestamp": time.time(),
                    "ledger": data
                }
            return data
    except Exception:
        return default_state

def save_ledger(ledger_path, state):
    """
    Saves the full state dictionary (including heat and ledger) to disk.
    """
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def log_structured(correlation_id, chain_name, step, outcome, status_msg="", extra=None):
    """Prints a structured JSON log for observability."""
    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "status_msg": status_msg,
        "actor_id": "system"
    }
    if extra:
        log_entry.update(extra)
    print(f"JSON_LOG: {json.dumps(log_entry)}")

def main(correlation_id="direct-run"):
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

    state = load_ledger(ledger_path)
    ledger = state["ledger"]

    # Apply passive cooling
    old_heat, new_heat = apply_cooling(state)
    if old_heat != new_heat:
        log_structured(correlation_id, "dna_batch", "cooling", "success",
                      f"System cooled from {old_heat:.2f} to {new_heat:.2f}")

    # Save state if cooling happened
    if old_heat != new_heat:
        save_ledger(ledger_path, state)

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
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

    from utils.dna_calculator import RuleParseError

    new_processed_count = 0
    processed_in_batch = set()

    for dna_str in dna_list:
        idempotency_key = dna_str

        # Intra-batch deduplication
        if idempotency_key in processed_in_batch:
            continue

        if idempotency_key in ledger:
            log_structured(correlation_id, "dna_batch", "dedupe", "skipped",
                          f"Key {idempotency_key} already in ledger.",
                          {"idempotency_key": idempotency_key})
            continue

        log_structured(correlation_id, "dna_batch", "parse", "processing",
                      f"Parsing {dna_str}", {"idempotency_key": idempotency_key})

        try:
            # Thermal Check - pre-calculate gain
            # We don't know the rule yet, so we'll do a quick check
            # For simplicity, if it's VOL, it's 0.3, else 0.1
            tentative_gain = 0.3 if dna_str.startswith("VOL") else 0.1
            if state["system_heat"] + tentative_gain > MAX_HEAT:
                log_structured(correlation_id, "dna_batch", "thermal_check", "refused",
                              f"{MSG_REFUSAL} {MSG_HINT}",
                              {"system_heat": state["system_heat"]})
                # Break to stop processing further items in this batch
                break

            result = calculator.parse(dna_str)
            heat_gain = calculate_heat_delta(result)
            state["system_heat"] += heat_gain

            # Apply Data Degradation (Noise) if over threshold
            noise_applied = False
            if state["system_heat"] > NOISE_THRESHOLD:
                noise_applied = True
                # In a real system we'd mutate the 'result' here.
                # For this MVP, we'll just log it as a consequence.

            entry = {
                'dna_sequence': dna_str,
                'rule': result['rule'],
                'parsed': result['values'],
                'thermal_status': "degraded" if noise_applied else "clean"
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_str
            flat['rule'] = result['rule']
            flat['thermal_status'] = entry['thermal_status']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

            if noise_applied:
                 log_structured(correlation_id, "dna_batch", "process", "success",
                              MSG_CONSEQUENCE.format(heat=state['system_heat']),
                              {"system_heat": state["system_heat"], "idempotency_key": idempotency_key})
            else:
                 log_structured(correlation_id, "dna_batch", "process", "success",
                              f"Processed {dna_str} clean. Heat: {state['system_heat']:.2f}",
                              {"system_heat": state["system_heat"], "idempotency_key": idempotency_key})

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna_sequence': dna_str,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna_sequence': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"
            log_structured(correlation_id, "dna_batch", "process", "error", str(e),
                          {"idempotency_key": idempotency_key})

        # Update ledger for this item
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1
        processed_in_batch.add(idempotency_key)

    if new_processed_count == 0 and state["system_heat"] == old_heat:
        print("[OK] No new DNA strings and no heat change.")
        return

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
                # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    # Save ledger if heat changed or new items processed
    save_ledger(ledger_path, state)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
