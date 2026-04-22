#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
import getpass
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    NO_NEW_DNA = "NO_NEW_DNA"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"

@dataclass
class ParsedDNA:
    dna: str
    rule: str
    values: Dict[str, Any]

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def log_observability(chain_name: str, step: str, outcome: Outcome, latency_ms: int = 0,
                      idempotency_key: str = "N/A", error_message: Optional[str] = None,
                      correlation_id: Optional[str] = None):
    timestamp = datetime.now(timezone.utc).isoformat()
    cid = correlation_id or str(uuid.uuid4())
    actor_id = getpass.getuser()
    error_part = f" | {error_message}" if error_message else ""

    log_line = f"{timestamp} | {cid} | {chain_name} | {step} | {outcome.value} | {latency_ms}ms | {actor_id} | {idempotency_key}{error_part}"
    print(log_line)

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

def main(project_root: Optional[str] = None):
    start_time = time.time()
    chain_name = "DNA_BATCH_PARSING"
    correlation_id = str(uuid.uuid4())
    log_observability(chain_name, "START", Outcome.START, correlation_id=correlation_id)

    # Determine file paths
    if project_root is None:
        project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(chain_name, "END", Outcome.ERROR, error_message=f"Input file not found: {input_file}", correlation_id=correlation_id)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(chain_name, "END", Outcome.ERROR, error_message=str(e), correlation_id=correlation_id)
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(chain_name, "END", Outcome.ERROR, error_message=str(e), correlation_id=correlation_id)
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(chain_name, "END", Outcome.NO_NEW_DNA, correlation_id=correlation_id)
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
    errors_count = 0
    success_count = 0

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability(chain_name, "PROCESS", Outcome.SKIPPED, idempotency_key=idempotency_key, correlation_id=correlation_id)
            continue

        log_observability(chain_name, "PROCESS", Outcome.PROCESSING, idempotency_key=idempotency_key, correlation_id=correlation_id)

        try:
            result = calculator.parse(dna_str)
            parsed_dto = ParsedDNA(dna=dna_str, rule=result['rule'], values=result['values'])

            entry = {
                'dna': parsed_dto.dna,
                'rule': parsed_dto.rule,
                'parsed': parsed_dto.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(parsed_dto.rule, parsed_dto.values)
            flat['dna'] = parsed_dto.dna
            flat['rule'] = parsed_dto.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = Outcome.SUCCESS
            success_count += 1
            error_msg = None

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

            outcome = Outcome.ERROR
            error_msg = str(e)
            errors_count += 1

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        log_observability(chain_name, "PROCESS_DONE", outcome, idempotency_key=idempotency_key, error_message=error_msg, correlation_id=correlation_id)
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    if new_processed_count > 0:
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

                log_observability(chain_name, "COMMIT", Outcome.SUCCESS, correlation_id=correlation_id)

            except Exception as e:
                log_observability(chain_name, "COMMIT", Outcome.ERROR, error_message=str(e), correlation_id=correlation_id)
                raise PersistenceError("Failed to write output files atomically") from e

    latency = int((time.time() - start_time) * 1000)

    # Determine final batch outcome
    if new_processed_count == 0:
        final_outcome = Outcome.SKIPPED
    elif errors_count > 0 and success_count > 0:
        final_outcome = Outcome.PARTIAL_SUCCESS
    elif errors_count > 0:
        final_outcome = Outcome.ERROR
    else:
        final_outcome = Outcome.SUCCESS

    log_observability(chain_name, "END", final_outcome, latency_ms=latency, correlation_id=correlation_id)

if __name__ == '__main__':
    main()
