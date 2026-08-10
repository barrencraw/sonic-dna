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

from enum import Enum

class DNAStatus(str, Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'

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
    """Raised when saving the ledger file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing or moving output files fails."""
    pass
import datetime
import uuid

def log_structured(step, outcome, latency_ms=0, correlation_id=None, actor_id='system', chain_name='dna_batch_processing', idempotency_key=None, outcome_detail=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    log_data = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
        'correlation_id': correlation_id,
        'actor_id': actor_id,
        'chain_name': chain_name,
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail
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
    dir_name = os.path.dirname(ledger_path)
    ensure_folder(dir_name)
    tmp_file = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix="ledger_", suffix=".tmp")
        tmp_file = tmp_path
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically: {e}") from e

class BatchResult:
    def __init__(self, status, processed_count, total_ledger_items):
        self.status = status
        self.processed_count = processed_count
        self.total_ledger_items = total_ledger_items

    def __repr__(self):
        return f"BatchResult(status={self.status!r}, processed_count={self.processed_count}, total_ledger_items={self.total_ledger_items})"

def run_batch(correlation_id=None):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())
    log_structured('start', 'success', correlation_id=correlation_id)
    error_occurred = False

    try:
        # Determine file paths
        project_root = os.getcwd()
        raw_folder = os.path.join(project_root, 'data', 'raw')
        output_folder = os.path.join(project_root, 'data', 'output')
        ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
        ensure_folder(output_folder)

        input_file = os.path.join(raw_folder, 'toSequence.txt')
        if not os.path.isfile(input_file):
            log_structured('read_input', 'failure', correlation_id=correlation_id, outcome_detail="Input file not found")
            raw_ledger = load_ledger(ledger_path)
            ledger_dict = raw_ledger.get('ledger', raw_ledger) if isinstance(raw_ledger, dict) else {}
            return BatchResult('NO_NEW_ITEMS', 0, len(ledger_dict))

        # Instantiate calculator
        try:
            calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
        except Exception as e:
            raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

        # Read DNA strings
        try:
            dna_list = read_input_file(input_file)
        except Exception as e:
            raise InputReadError(f"Failed to read input file: {input_file}") from e

        raw_ledger = load_ledger(ledger_path)
        if isinstance(raw_ledger, dict) and 'ledger' in raw_ledger:
            ledger_dict = raw_ledger['ledger']
        elif isinstance(raw_ledger, dict):
            ledger_dict = raw_ledger
        else:
            ledger_dict = {}

        if not dna_list:
            log_structured('end', 'success', correlation_id=correlation_id, outcome_detail="No DNA strings to process")
            return BatchResult('NO_NEW_ITEMS', 0, len(ledger_dict))

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
        all_flattened_keys = set(['dna', 'dna_sequence'])
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
            if idempotency_key in ledger_dict:
                log_structured(
                    'parse_dna',
                    'skipped',
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Deduplicated: already exists in ledger with outcome {ledger_dict[idempotency_key].get('terminal_outcome')}"
                )
                continue

            try:
                result = calculator.parse(dna_str)
                outcome_status = DNAStatus.SUCCESS
                entry = {
                    'dna': dna_str,
                    'dna_sequence': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_str
                flat['dna_sequence'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome_detail = f"Successfully parsed rule {result['rule']}"

            except RuleParseError as e:
                outcome_status = DNAStatus.ERROR
                entry = {
                    'dna': dna_str,
                    'dna_sequence': dna_str,
                    'error': str(e)
                }
                parsed_json.append(entry)

                flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome_detail = f"Parse error: {str(e)}"

            ledger_dict[idempotency_key] = {
                'terminal_outcome': outcome_status.value,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
            }
            new_processed_count += 1
            log_structured(
                'parse_dna',
                outcome_status.value,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail
            )

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
                    fieldnames = sorted(list(all_flattened_keys))
                    if 'dna' not in fieldnames:
                        fieldnames.append('dna')
                    if 'dna_sequence' not in fieldnames:
                        fieldnames.append('dna_sequence')
                    fieldnames = sorted(list(set(fieldnames)))

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
                    log_structured('atomic_write', 'success', correlation_id=correlation_id, outcome_detail="Successfully saved outputs atomically")
                except Exception as e:
                    raise AtomicWriteError(f"Failed to write output files atomically: {e}") from e

            # Save ledger atomically
            if isinstance(raw_ledger, dict) and 'ledger' in raw_ledger:
                raw_ledger['ledger'] = ledger_dict
                if 'system_state' not in raw_ledger:
                    raw_ledger['system_state'] = {}
                raw_ledger['system_state']['last_processed_timestamp'] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
                to_save = raw_ledger
            else:
                to_save = ledger_dict

            save_ledger(ledger_path, to_save)

        status_val = 'SUCCESS' if new_processed_count > 0 else 'NO_NEW_ITEMS'
        latency = int((time.time() - start_time) * 1000)
        log_structured(
            'end',
            'success',
            latency_ms=latency,
            correlation_id=correlation_id,
            outcome_detail=f"Batch finished. status={status_val}, processed_count={new_processed_count}, total_ledger_items={len(ledger_dict)}"
        )
        return BatchResult(status_val, new_processed_count, len(ledger_dict))

    except Exception as e:
        error_occurred = True
        latency = int((time.time() - start_time) * 1000)
        log_structured(
            'run_batch',
            'failure',
            latency_ms=latency,
            correlation_id=correlation_id,
            outcome_detail=str(e)
        )
        raise

    finally:
        try:
            pass
        except Exception as cleanup_err:
            log_structured('cleanup_failure', 'failure', correlation_id=correlation_id, outcome_detail=str(cleanup_err))
            if not error_occurred:
                raise

main = run_batch

if __name__ == '__main__':
    run_batch()
