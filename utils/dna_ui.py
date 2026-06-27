#!/usr/bin/env python3
import os
import json
import csv
import time
from utils.dna_calculator import DNACalculator, RuleParseError

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequences = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_sequences.append(s)
    return dna_sequences

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
from enum import Enum

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def log_structured(correlation_id, chain_name, step, outcome, actor_id=None, idempotency_key=None, latency_ms=None, error_detail=None):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
    }
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

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def main(correlation_id="internal-unknown", actor_id="system"):
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
        log_structured(correlation_id, "dna_batch", "load_rules", DNAStatus.ERROR.value, actor_id=actor_id, error_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequences = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, "dna_batch", "read_input", DNAStatus.ERROR.value, actor_id=actor_id, error_detail=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequences:
        log_structured(correlation_id, "dna_batch", "read_input", DNAStatus.SKIPPED.value, actor_id=actor_id, error_detail="Empty input file")
        return

    ledger = load_ledger(ledger_path)

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
    for dna_sequence in dna_sequences:
        item_start_time = time.time()
        idempotency_key = dna_sequence
        outcome = DNAStatus.ERROR.value

        if idempotency_key in ledger:
            log_structured(correlation_id, "dna_batch", "process_item", DNAStatus.SKIPPED.value,
                           actor_id=actor_id, idempotency_key=idempotency_key, error_detail="Idempotency hit")
            continue

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
            log_structured(correlation_id, "dna_batch", "process_item", outcome,
                           actor_id=actor_id, idempotency_key=idempotency_key,
                           latency_ms=int((time.time() - item_start_time) * 1000))

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
            outcome = f"{DNAStatus.ERROR.value}: {str(e)}"
            log_structured(correlation_id, "dna_batch", "process_item", DNAStatus.ERROR.value,
                           actor_id=actor_id, idempotency_key=idempotency_key,
                           latency_ms=int((time.time() - item_start_time) * 1000), error_detail=str(e))

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

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
            log_structured(correlation_id, "dna_batch", "persistence", DNAStatus.ERROR.value, actor_id=actor_id, error_detail=str(e))
            raise PersistenceError("Failed to write output files atomically") from e

    log_structured(correlation_id, "dna_batch", "batch_complete", DNAStatus.SUCCESS.value, actor_id=actor_id)

    if new_processed_count > 0:
        # Save ledger
        save_ledger(ledger_path, ledger)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
