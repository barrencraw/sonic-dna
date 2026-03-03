#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError
from utils.observability import StructuredLogger, Timer

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_strings = []
    if os.path.exists(input_path):
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_strings.append(s)
    return dna_strings

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

class ProcessingOutcome(Enum):
    SUCCESS = "success"
    ERROR = "error"
    DEDUPE = "dedupe"

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

def run_batch(correlation_id=None):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    logger = StructuredLogger(chain_name="dna_processing", correlation_id=correlation_id)
    logger.log(step="start", outcome="started")

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        logger.log(step="load_rules", outcome="error", error=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_strings = read_input_file(input_file)
    except Exception as e:
        logger.log(step="read_input", outcome="error", error=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_strings:
        logger.log(step="read_input", outcome="warn", message="No DNA strings found")
        logger.log(step="terminal", outcome="success", message="No work to do")
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

    new_processed_count = 0
    for dna_string in dna_strings:
        idempotency_key = dna_string
        if idempotency_key in ledger:
            outcome_val = ledger[idempotency_key]['terminal_outcome']
            logger.log(step="idempotency_check", outcome="dedupe", idempotency_key=idempotency_key, terminal_outcome=outcome_val)
            continue

        with Timer() as timer:
            try:
                result = calculator.parse(dna_string)
                entry = result.to_dict()
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result.rule, result.values)
                flat['dna'] = dna_string
                flat['rule'] = result.rule
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome_status = ProcessingOutcome.SUCCESS
                outcome_detail = "success"

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_string,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna': dna_string, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome_status = ProcessingOutcome.ERROR
                outcome_detail = f"error: {str(e)}"

            logger.log(
                step="parse_dna",
                outcome=outcome_status.value,
                latency_ms=timer.interval,
                idempotency_key=idempotency_key
            )

        ledger[idempotency_key] = {
            'terminal_outcome': outcome_detail,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
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
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                logger.log(step="persistence", outcome="error", error=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

        # Save ledger
        save_ledger(ledger_path, ledger)

    logger.log(step="terminal", outcome="success", new_processed_count=new_processed_count, total_in_ledger=len(ledger))

if __name__ == '__main__':
    run_batch()
