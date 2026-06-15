#!/usr/bin/env python3
import os
import json
import csv
import time
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    PROCESSING = "processing"

def log_structured(step, outcome, correlation_id=None, dna_sequence=None, latency_ms=None, error=None):
    """
    Standardized JSON logging for the DNA batch chain.
    """
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id or "unknown",
        "chain_name": "dna_batch_processor",
        "step": step,
        "outcome": outcome,
    }
    if dna_sequence:
        log_entry["dna_sequence"] = dna_sequence
    if latency_ms is not None:
        log_entry["latency_ms"] = latency_ms
    if error:
        log_entry["error_message"] = str(error)

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

import tempfile

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when the system heat exceeds MAX_HEAT."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass
MAX_HEAT = 10.0
HEAT_PER_ITEM = 1.0
COOLING_RATE_PER_SEC = 0.01

MSG_CONSEQUENCE = "SYSTEM_FATIGUE_LOCKOUT"
MSG_REFUSAL = "THERMAL_LIMIT_EXCEEDED"
MSG_HINT = "Wait for system cooling or reduce batch size."

def load_ledger(ledger_path):
    """
    Loads the structured ledger state, handling migration from legacy formats.
    """
    state = {
        "system_heat": 0.0,
        "last_processed_timestamp": 0.0,
        "ledger": {}
    }

    # 1. Try modern path
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "ledger" in data:
                    return data
                else:
                    # Legacy flat format at modern path
                    state["ledger"] = data
                    return state
        except Exception:
            return state

    # 2. Try legacy path (migration)
    project_root = os.getcwd()
    legacy_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    if os.path.exists(legacy_path):
        try:
            with open(legacy_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "ledger" in data:
                    state = data
                else:
                    state["ledger"] = data
            return state
        except Exception:
            pass

    return state

def main(correlation_id=None):
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'ledger.json')
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
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    state = load_ledger(ledger_path)
    ledger = state["ledger"]

    # Apply cooling
    now = time.time()
    if state["last_processed_timestamp"] > 0:
        elapsed = now - state["last_processed_timestamp"]
        state["system_heat"] = max(0.0, state["system_heat"] - (elapsed * COOLING_RATE_PER_SEC))

    # Check thermal fatigue before processing
    new_items_count = sum(1 for d in dna_list if d not in ledger)
    projected_heat = state["system_heat"] + (new_items_count * HEAT_PER_ITEM)

    if projected_heat > MAX_HEAT:
        log_structured(
            step="batch_init",
            outcome=DNAStatus.ERROR.value,
            correlation_id=correlation_id,
            error=f"{MSG_REFUSAL}: {projected_heat:.2f} > {MAX_HEAT}"
        )
        print(f"[CRITICAL] {MSG_CONSEQUENCE}: {MSG_REFUSAL}")
        print(f"           Current Heat: {state['system_heat']:.2f}, Projected: {projected_heat:.2f}")
        print(f"           {MSG_HINT}")
        raise ThermalOverloadError(f"{MSG_REFUSAL}: {projected_heat:.2f}")

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                raw_data = json.load(jf)
                if isinstance(raw_data, list):
                    for entry in raw_data:
                        # Migrate legacy 'dna' field to 'dna_sequence'
                        if 'dna' in entry and 'dna_sequence' not in entry:
                            entry['dna_sequence'] = entry.pop('dna')
                        parsed_json.append(entry)
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
                    # Migrate headers
                    headers = []
                    for h in reader.fieldnames:
                        if h == 'dna':
                            headers.append('dna_sequence')
                        else:
                            headers.append(h)
                    all_flattened_keys = set(headers)

                    for row in reader:
                        # Migrate row data
                        if 'dna' in row:
                            row['dna_sequence'] = row.pop('dna')
                        csv_rows.append(row)
        except Exception:
            pass

    from utils.dna_calculator import RuleParseError

    new_processed_count = 0
    for dna_sequence in dna_list:
        idempotency_key = dna_sequence
        start_time = time.time()

        if idempotency_key in ledger:
            terminal_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS.value)
            log_structured(
                step="parse_item",
                outcome=DNAStatus.SKIPPED.value,
                correlation_id=correlation_id,
                dna_sequence=dna_sequence
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
        outcome = "unknown_error"

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        latency_ms = int((time.time() - start_time) * 1000)
        log_structured(
            step="parse_item",
            outcome=outcome,
            correlation_id=correlation_id,
            dna_sequence=dna_sequence,
            latency_ms=latency_ms
        )

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        state["system_heat"] += HEAT_PER_ITEM
        state["last_processed_timestamp"] = time.time()
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    # Use data folder for temp to ensure same filesystem for ledger and output
    data_dir = os.path.dirname(output_folder)
    with tempfile.TemporaryDirectory(dir=data_dir) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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

            # 3) Write Ledger to temp
            with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                json.dump(state, lf, indent=2)
                lf.flush()
                os.fsync(lf.fileno())

            # 4) Atomic rename (commit)
            # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)

        except Exception as e:
            raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
