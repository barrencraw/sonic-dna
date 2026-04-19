#!/usr/bin/env python3
import os
import json
import csv
import time
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError, ParsedDNA

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    NO_NEW_DNA = "NO_NEW_DNA"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"

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

import uuid
import getpass
from datetime import datetime, timezone

def log_observability(chain_name, step, outcome, latency_ms=0, correlation_id=None, idempotency_key=None, error_message=None):
    """
    Standardized structured logging for SonicDNA.
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else str(outcome),
        "latency_ms": latency_ms,
        "actor_id": getpass.getuser(),
        "idempotency_key": idempotency_key
    }
    if error_message:
        log_entry["error_message"] = error_message

    print(json.dumps(log_entry))

def main(data_dir=None):
    start_time = time.time()
    correlation_id = str(uuid.uuid4())
    chain_name = "DNA_Batch_Chain"

    log_observability(chain_name, "start", Outcome.START, correlation_id=correlation_id)

    # Determine file paths
    project_root = data_dir or os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(chain_name, "read_input", Outcome.ERROR, correlation_id=correlation_id, error_message=f"Input file not found: {input_file}")
        log_observability(chain_name, "end", Outcome.END, correlation_id=correlation_id)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(chain_name, "load_rules", Outcome.ERROR, correlation_id=correlation_id, error_message=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(chain_name, "read_input", Outcome.ERROR, correlation_id=correlation_id, error_message=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(chain_name, "process_dna", Outcome.NO_NEW_DNA, correlation_id=correlation_id)
        log_observability(chain_name, "end", Outcome.END, correlation_id=correlation_id)
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
    errors_count = 0
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability(chain_name, "dedupe", Outcome.SKIPPED, correlation_id=correlation_id, idempotency_key=idempotency_key)
            continue

        log_observability(chain_name, "process_item", Outcome.PROCESSING, correlation_id=correlation_id, idempotency_key=idempotency_key)

        try:
            parsed_dna = calculator.parse(dna_str)
            entry = {
                'dna': parsed_dna.dna,
                'rule': parsed_dna.rule,
                'parsed': parsed_dna.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(parsed_dna.rule, parsed_dna.values)
            flat['dna'] = parsed_dna.dna
            flat['rule'] = parsed_dna.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS

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
            errors_count += 1
            log_observability(chain_name, "item_complete", outcome, correlation_id=correlation_id, idempotency_key=idempotency_key, error_message=str(e))
        else:
            log_observability(chain_name, "item_complete", outcome, correlation_id=correlation_id, idempotency_key=idempotency_key)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

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

                # 3) Write ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    latency_ms = int((time.time() - start_time) * 1000)

    final_outcome = Outcome.SUCCESS
    if new_processed_count == 0:
        final_outcome = Outcome.NO_NEW_DNA
    elif errors_count > 0:
        if errors_count == new_processed_count:
            final_outcome = Outcome.ERROR
        else:
            final_outcome = Outcome.PARTIAL_SUCCESS

    log_observability(chain_name, "batch_complete", final_outcome, latency_ms=latency_ms, correlation_id=correlation_id)
    log_observability(chain_name, "end", Outcome.END, correlation_id=correlation_id)

    if new_processed_count > 0:
        print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
