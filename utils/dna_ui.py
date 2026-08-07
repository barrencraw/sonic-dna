#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import uuid
from utils.dna_calculator import DNACalculator, RuleParseError

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_sequence_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_sequence_list.append(s)
    return dna_sequence_list

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

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic write of output files fails."""
    pass

from enum import Enum

class DNAStatus(str, Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'

class BatchResult:
    def __init__(self, status: str, processed_count: int, total_ledger_items: int):
        self.status = status
        self.processed_count = processed_count
        self.total_ledger_items = total_ledger_items

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key=None, outcome_detail=None):
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if timestamp.endswith("+00:00"):
        timestamp = timestamp[:-6] + "Z"

    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "N/A",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": int(latency_ms),
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or "N/A"
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    # Ensure parent folder of ledger exists
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(ledger_path))
    try:
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, ledger_path)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically to {ledger_path}") from e

def run_batch(correlation_id=None):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())
    actor_id = 'system'
    chain_name = 'dna_batch_parsing'
    error_occurred = False

    log_structured(correlation_id, actor_id, chain_name, 'batch_started', 'processing', 0)

    try:
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
            raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

        # Read DNA strings
        try:
            if not os.path.isfile(input_file):
                raise InputReadError(f"Input file not found: {input_file}")
            dna_sequence_list = read_input_file(input_file)
        except Exception as e:
            if isinstance(e, InputReadError):
                raise
            raise InputReadError(f"Failed to read input file: {input_file}") from e

        ledger = load_ledger(ledger_path)

        if not dna_sequence_list:
            latency_ms = (time.time() - start_time) * 1000
            log_structured(correlation_id, actor_id, chain_name, 'batch_completed', 'no_new_items', latency_ms, outcome_detail="No DNA strings found in toSequence.txt")
            return BatchResult('NO_NEW_ITEMS', 0, len(ledger))

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
        for dna_sequence in dna_sequence_list:
            item_start_time = time.time()
            idempotency_key = dna_sequence
            if idempotency_key in ledger:
                latency_ms = (time.time() - item_start_time) * 1000
                log_structured(
                    correlation_id, actor_id, chain_name, 'deduplication', 'skipped', latency_ms,
                    idempotency_key=idempotency_key, outcome_detail='Sequence already in ledger'
                )
                continue

            try:
                result = calculator.parse(dna_sequence)
                entry = {
                    'dna': dna_sequence,
                    'dna_sequence': dna_sequence,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_sequence
                flat['dna_sequence'] = dna_sequence
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.SUCCESS.value

                latency_ms = (time.time() - item_start_time) * 1000
                log_structured(
                    correlation_id, actor_id, chain_name, 'parse_success', 'success', latency_ms,
                    idempotency_key=idempotency_key, outcome_detail='Successfully parsed sequence'
                )

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_sequence,
                    'dna_sequence': dna_sequence,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {
                    'dna': dna_sequence,
                    'dna_sequence': dna_sequence,
                    'error': str(e)
                }
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR.value

                latency_ms = (time.time() - item_start_time) * 1000
                log_structured(
                    correlation_id, actor_id, chain_name, 'parse_error', 'error', latency_ms,
                    idempotency_key=idempotency_key, outcome_detail=str(e)
                )

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1

        # Define output file paths once at the beginning/end to prevent UnboundLocalError
        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

        if new_processed_count > 0:
            # Save ledger atomically
            save_ledger(ledger_path, ledger)

            # ATOMIC WRITE PATTERN:
            # 1. Write to a temporary directory in the same filesystem as the output folder
            # 2. Flush and sync files to ensure they are on disk
            # 3. Rename them to their final destination (atomic on most OSes)
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
                    raise AtomicWriteError("Failed to write output files atomically") from e

        batch_latency = (time.time() - start_time) * 1000
        log_structured(
            correlation_id, actor_id, chain_name, 'batch_completed',
            'success' if new_processed_count > 0 else 'no_new_items', batch_latency,
            outcome_detail=f"Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}"
        )

        if new_processed_count > 0:
            return BatchResult('SUCCESS', new_processed_count, len(ledger))
        else:
            return BatchResult('NO_NEW_ITEMS', 0, len(ledger))

    except Exception as e:
        error_occurred = True
        raise e
    finally:
        try:
            pass
        except Exception as cleanup_err:
            latency_ms = (time.time() - start_time) * 1000
            log_structured(correlation_id, actor_id, chain_name, 'cleanup_failure', 'error', latency_ms, outcome_detail=str(cleanup_err))
            if not error_occurred:
                raise cleanup_err

main = run_batch

if __name__ == '__main__':
    run_batch()
