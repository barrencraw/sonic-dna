#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
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

def log_structured(step, outcome, correlation_id=None, actor_id=None, idempotency_key=None, latency_ms=None, error_detail=None):
    """
    Standardized structured logging.
    """
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "chain_name": "dna_batch_processing",
        "step": step,
        "outcome": outcome
    }
    if correlation_id: log_entry["correlation_id"] = correlation_id
    if actor_id: log_entry["actor_id"] = actor_id
    if idempotency_key: log_entry["idempotency_key"] = idempotency_key
    if latency_ms is not None: log_entry["latency_ms"] = latency_ms
    if error_detail: log_entry["error_detail"] = error_detail

    print(f"JSON_LOG: {json.dumps(log_entry)}")

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def main(correlation_id=None, actor_id=None):
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')
    ensure_folder(output_folder)

    log_structured("batch_start", "success", correlation_id=correlation_id, actor_id=actor_id)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured("batch_end", "error", correlation_id=correlation_id, actor_id=actor_id, error_detail=f"Input file not found: {input_file}")
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured("batch_end", "error", correlation_id=correlation_id, actor_id=actor_id, error_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured("batch_end", "error", correlation_id=correlation_id, actor_id=actor_id, error_detail=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured("batch_end", "success", correlation_id=correlation_id, actor_id=actor_id, error_detail="No DNA strings found")
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)

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
    for dna_str in dna_list:
        idempotency_key = dna_str
        item_start = time.time()
        error_msg = None

        if idempotency_key in ledger:
            log_structured("item_process", "skipped", correlation_id=correlation_id, actor_id=actor_id, idempotency_key=idempotency_key, latency_ms=0)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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
            error_msg = str(e)

        latency = int((time.time() - item_start) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        log_structured("item_process", outcome, correlation_id=correlation_id, actor_id=actor_id,
                       idempotency_key=idempotency_key, latency_ms=latency,
                       error_detail=error_msg)

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count == 0:
        log_structured("batch_end", "success", correlation_id=correlation_id, actor_id=actor_id, error_detail="All items skipped")
        print("[OK] All DNA strings were already processed (idempotency hits).")
        return

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)

    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
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
                json.dump(ledger, lf, indent=2)
                lf.flush()
                os.fsync(lf.fileno())

            # 4) Atomic rename (commit)
            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)

        except Exception as e:
            log_structured("batch_end", "error", correlation_id=correlation_id, actor_id=actor_id, error_detail=f"Persistence error: {str(e)}")
            raise PersistenceError("Failed to write output files atomically") from e

    log_structured("batch_end", "success", correlation_id=correlation_id, actor_id=actor_id)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON   → {json_output_path}")
    print(f"     CSV    → {csv_output_path}")
    print(f"     Ledger → {ledger_path}")

if __name__ == '__main__':
    main()
