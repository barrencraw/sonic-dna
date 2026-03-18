#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
import datetime
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
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def log_observability(correlation_id, actor_id, step, outcome, latency_ms=0, idempotency_key=None):
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key
    }
    print(f"[OBSERVABILITY] {json.dumps(log_entry)}")

def main(correlation_id=None, actor_id="manual"):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    log_observability(correlation_id, actor_id, "batch_start", "STARTED")

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(correlation_id, actor_id, "batch_end", "ERROR_READ_INPUT")
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(correlation_id, actor_id, "batch_end", "NO_NEW_DATA")
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, actor_id, "batch_end", "ERROR_LOAD_RULES")
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    ledger = load_ledger(ledger_path)

    # 1) Load existing JSON output
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                content = json.load(jf)
                if isinstance(content, list):
                    parsed_json = content
        except Exception:
            pass

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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability(correlation_id, actor_id, "process_dna", "DEDUPE", idempotency_key=idempotency_key)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        start_time = time.time()
        outcome = "UNKNOWN"
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
            outcome = "SUCCESS"

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
            outcome = "ERROR"

        latency_ms = int((time.time() - start_time) * 1000)

        # Update ledger (in-memory)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'correlation_id': correlation_id
        }

        log_observability(correlation_id, actor_id, "process_dna", outcome, latency_ms=latency_ms, idempotency_key=idempotency_key)
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count == 0:
        log_observability(correlation_id, actor_id, "batch_end", "NO_NEW_DATA")
        print("[OK] No new DNA strings to process.")
        return

    # ATOMIC COMMIT PATTERN
    # To improve multi-file atomicity, we write all files to a temporary directory
    # on the same filesystem, and then replace them one by one.
    # While not a single transaction, it minimizes the window of inconsistency.
    with tempfile.TemporaryDirectory(dir=os.path.dirname(ledger_path)) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'toSequence_parsed.json')
        tmp_csv = os.path.join(tmp_dir, 'toSequence_parsed.csv')
        tmp_ledger = os.path.join(tmp_dir, 'processed_ledger.json')

        try:
            # Write JSON
            with open(tmp_json, 'w', encoding='utf-8') as jf:
                json.dump(parsed_json, jf, indent=2)
                jf.flush()
                os.fsync(jf.fileno())

            # Write CSV
            fieldnames = sorted(all_flattened_keys)
            with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                writer = csv.DictWriter(cf, fieldnames=fieldnames)
                writer.writeheader()
                for row in csv_rows:
                    out = {k: row.get(k, '') for k in fieldnames}
                    writer.writerow(out)
                cf.flush()
                os.fsync(cf.fileno())

            # Write Ledger
            with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                json.dump(ledger, lf, indent=2)
                lf.flush()
                os.fsync(lf.fileno())

            # Atomic Swap
            # Order: Data first, then Ledger (source of truth for idempotency)
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)

        except Exception as e:
            log_observability(correlation_id, actor_id, "batch_end", "PERSISTENCE_ERROR")
            raise PersistenceError("Failed to write output files atomically") from e

    log_observability(correlation_id, actor_id, "batch_end", "SUCCESS")
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
