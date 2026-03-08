#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def main(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    print(f"[OBSERVABILITY] correlation_id={correlation_id} step=start chain_name=dna_batch_parser")

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        print(f"[OBSERVABILITY] correlation_id={correlation_id} step=terminal outcome=error reason=input_file_missing")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        print(f"[OBSERVABILITY] correlation_id={correlation_id} step=terminal outcome=error reason=rule_load_failure")
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        print(f"[OBSERVABILITY] correlation_id={correlation_id} step=terminal outcome=error reason=read_failure")
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        print(f"[OBSERVABILITY] correlation_id={correlation_id} step=terminal outcome=success reason=empty_input")
        return

    ledger = load_ledger(ledger_path)

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                data = json.load(jf)
                if isinstance(data, list):
                    # Filter by ledger to handle partial successes from previous runs
                    parsed_json = [item for item in data if item.get('dna') in ledger or (item.get('dna') is None and item.get('error'))]
        except Exception:
            # If the file is corrupted, we ignore its contents.
            # In a real system we might want to backup the corrupted file.
            pass

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
                    # Filter by ledger to handle partial successes from previous runs
                    csv_rows = [row for row in reader if row.get('dna') in ledger]
        except Exception:
            pass

    new_processed_count = 0
    start_time = time.time()

    pending_json = []
    pending_csv = []
    pending_ledger_updates = {}

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger or idempotency_key in pending_ledger_updates:
            outcome = ledger[idempotency_key]['terminal_outcome'] if idempotency_key in ledger else pending_ledger_updates[idempotency_key]['terminal_outcome']
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={outcome}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            pending_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            pending_csv.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except RuleParseError as e:
            # On parse error, record as error entry
            entry = {
                'dna': dna_str,
                'error': str(e)
            }
            pending_json.append(entry)
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e)}
            pending_csv.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        pending_ledger_updates[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count == 0:
        print("[OK] No new DNA strings to process (all deduped).")
        print(f"[OBSERVABILITY] correlation_id={correlation_id} step=terminal outcome=success items_processed=0")
        return

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination
    print(f"[OBSERVABILITY] correlation_id={correlation_id} step=persistence_start")

    # We use data/ as the base for temp dir to cover both data/output and data/
    with tempfile.TemporaryDirectory(dir=os.path.join(project_root, 'data')) as tmp_dir:
        # Commit pending updates ONLY inside the atomic block (or logically right before it)
        # to ensure local state remains consistent with what we are about to write.
        current_parsed_json = parsed_json + pending_json
        current_csv_rows = csv_rows + pending_csv
        current_ledger = ledger.copy()
        current_ledger.update(pending_ledger_updates)

        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

        try:
            # 1) Write JSON output to temp
            with open(tmp_json, 'w', encoding='utf-8') as jf:
                json.dump(current_parsed_json, jf, indent=2)
                jf.flush()
                os.fsync(jf.fileno())

            # 2) Write CSV output to temp
            fieldnames = sorted(all_flattened_keys)
            with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                writer = csv.DictWriter(cf, fieldnames=fieldnames)
                writer.writeheader()
                for row in current_csv_rows:
                    out = {k: row.get(k, '') for k in fieldnames}
                    writer.writerow(out)
                cf.flush()
                os.fsync(cf.fileno())

            # 3) Write Ledger to temp
            with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                json.dump(current_ledger, lf, indent=2)
                lf.flush()
                os.fsync(lf.fileno())

            # 4) Atomic renames (commit)
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)

            # Update in-memory state only after successful rename
            parsed_json.extend(pending_json)
            csv_rows.extend(pending_csv)
            ledger.update(pending_ledger_updates)

        except Exception as e:
            print(f"[OBSERVABILITY] correlation_id={correlation_id} step=terminal outcome=error reason=persistence_failure")
            raise PersistenceError(f"Failed to write output files atomically: {e}") from e

    latency_ms = int((time.time() - start_time) * 1000)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"[OBSERVABILITY] correlation_id={correlation_id} step=terminal outcome=success items_processed={new_processed_count} latency_ms={latency_ms}")

if __name__ == '__main__':
    main()
