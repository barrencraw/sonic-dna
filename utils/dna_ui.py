#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input files fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for writing or moving output/ledger files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when writing the ledger file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing JSON or CSV output files atomically fails."""
    pass

class DNAStatus:
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'

class BatchResult:
    def __init__(self, status, processed_count, total_ledger_items):
        self.status = status
        self.processed_count = processed_count
        self.total_ledger_items = total_ledger_items

    def __repr__(self):
        return f"BatchResult(status={self.status!r}, processed_count={self.processed_count}, total_ledger_items={self.total_ledger_items})"

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
    ledger_dir = os.path.dirname(ledger_path)
    tmp_path = None
    tmp_file = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=ledger_dir, prefix="ledger_tmp_")
        tmp_file = os.fdopen(fd, 'w', encoding='utf-8')
        json.dump(ledger, tmp_file, indent=2)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
        tmp_file.close()
        tmp_file = None
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        if tmp_file is not None:
            try:
                tmp_file.close()
            except Exception:
                pass
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise LedgerSaveError("Failed to save ledger atomically") from e

def log_structured(step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None, correlation_id=None, actor_id="system", chain_name="dna_batch_parsing"):
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        "timestamp": timestamp_str,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "system",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")

def run_batch(correlation_id=None):
    start_time = time.time()
    log_structured("start", "success", correlation_id=correlation_id)

    # Determine file paths defined once at the beginning
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured("completed", "skipped", latency_ms=int((time.time() - start_time) * 1000), outcome_detail="Input file not found", correlation_id=correlation_id)
        return BatchResult("NO_NEW_ITEMS", 0, len(load_ledger(ledger_path)))

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured("completed", "error", latency_ms=int((time.time() - start_time) * 1000), outcome_detail=str(e), correlation_id=correlation_id)
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured("completed", "error", latency_ms=int((time.time() - start_time) * 1000), outcome_detail=str(e), correlation_id=correlation_id)
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured("completed", "skipped", latency_ms=int((time.time() - start_time) * 1000), outcome_detail="No DNA strings found", correlation_id=correlation_id)
        return BatchResult("NO_NEW_ITEMS", 0, len(load_ledger(ledger_path)))

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
    error_occurred = False

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                log_structured("parse_sequence", "skipped", idempotency_key=idempotency_key, outcome_detail="Deduplication hit", correlation_id=correlation_id)
                continue

            item_start = time.time()
            try:
                result = calculator.parse(dna_str)
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
                outcome = DNAStatus.SUCCESS
                outcome_detail = "Successfully parsed sequence"
            except RuleParseError as e:
                parsed_json.append({
                    'dna': dna_str,
                    'dna_sequence': dna_str,
                    'error': str(e)
                })
                flat = {
                    'dna': dna_str,
                    'dna_sequence': dna_str,
                    'error': str(e)
                }
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR
                outcome_detail = f"Parse error: {str(e)}"

            # Maintain the ledger update and processed count increment inside the loop
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1
            log_structured(
                "parse_sequence",
                outcome,
                latency_ms=int((time.time() - item_start) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail,
                correlation_id=correlation_id
            )

        # Atomic output files write if new_processed_count > 0
        if new_processed_count > 0:
            # 1) Save ledger atomically
            save_ledger(ledger_path, ledger)

            # 2) Atomic JSON and CSV writes
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
                    # Make sure 'dna' and 'dna_sequence' are in fieldnames
                    for k in ['dna', 'dna_sequence']:
                        if k not in fieldnames:
                            fieldnames.append(k)
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

                except Exception as e:
                    raise AtomicWriteError("Failed to write output files atomically") from e

    except Exception as e:
        error_occurred = True
        log_structured("completed", "error", latency_ms=int((time.time() - start_time) * 1000), outcome_detail=str(e), correlation_id=correlation_id)
        raise e
    finally:
        try:
            pass
        except Exception as cleanup_err:
            log_structured("cleanup_failure", "error", outcome_detail=str(cleanup_err), correlation_id=correlation_id)
            if not error_occurred:
                raise cleanup_err

    # Final success/no_new_items logs
    status = "SUCCESS" if new_processed_count > 0 else "NO_NEW_ITEMS"
    log_structured("completed", "success", latency_ms=int((time.time() - start_time) * 1000), outcome_detail=f"Batch finished with status {status}", correlation_id=correlation_id)
    return BatchResult(status, new_processed_count, len(ledger))

# Maintain alias main for backwards compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
