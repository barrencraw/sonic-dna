#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
from utils.dna_calculator import DNACalculator, RuleParseError
from utils.dtos import DNAResult, ProcessingOutcome
from utils.observability import StructuredLogger

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

def main(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    logger = StructuredLogger(chain_name="dna_batch_processing")
    start_time = time.time()
    logger.log("start", "processing", correlation_id)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        logger.log("terminal", "error", correlation_id, extra={"error": "Input file not found"})
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        logger.log("terminal", "error", correlation_id, extra={"error": str(e)})
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        logger.log("terminal", "error", correlation_id, extra={"error": str(e)})
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        logger.log("terminal", "success", correlation_id, extra={"message": "No DNA strings found"})
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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            logger.log("processing_step", "dedupe", correlation_id, extra={"idempotency_key": idempotency_key})
            continue

        dna_start_time = time.time()
        result = calculator.parse(dna_str)

        if result.outcome == ProcessingOutcome.SUCCESS:
            entry = {
                'dna': dna_str,
                'rule': result.rule_name,
                'parsed': result.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result.rule_name, result.values)
            flat['dna'] = dna_str
            flat['rule'] = result.rule_name
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = ProcessingOutcome.SUCCESS.value
        else:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': result.error_message
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': result.error_message}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = ProcessingOutcome.ERROR.value

        dna_latency = (time.time() - dna_start_time) * 1000
        logger.log("processing_step", outcome.lower(), correlation_id,
                   latency_ms=dna_latency,
                   extra={"idempotency_key": idempotency_key})

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
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
            raise PersistenceError("Failed to write output files atomically") from e

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger)

    latency_ms = (time.time() - start_time) * 1000
    logger.log("terminal", "success", correlation_id, latency_ms=latency_ms,
               extra={"processed_count": new_processed_count})

if __name__ == '__main__':
    main()
