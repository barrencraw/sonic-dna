#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- ENUMS & DTOS ---

class DNAStatus(Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'

class BatchResult:
    def __init__(self, status: str, processed_count: int, total_ledger_items: int):
        self.status = status
        self.processed_count = processed_count
        self.total_ledger_items = total_ledger_items

    def __repr__(self):
        return f"BatchResult(status={self.status}, processed_count={self.processed_count}, total_ledger_items={self.total_ledger_items})"

# --- EXCEPTION TAXONOMY ---

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
    """Raised when input file cannot be read."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when ledger file cannot be saved."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when ledger file exists but cannot be loaded or parsed."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic write fails."""
    pass

# --- UTILITIES ---

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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Failed to load or parse ledger from {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger):
    temp_fd = None
    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(ledger_path))
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            temp_fd = None  # fd is now managed by 'with' statement and will be closed
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, ledger_path)
    except Exception as e:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except Exception:
                pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically to {ledger_path}") from e

def log_structured(correlation_id, step, outcome, latency_ms=0, actor_id="main_user", idempotency_key=None, outcome_detail=None, chain_name="dna_batch_chain"):
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "main_user",
        "chain_name": chain_name or "dna_batch_chain",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or "N/A"
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")

def run_batch(correlation_id=None):
    start_time = time.time()
    error_occurred = False
    new_processed_count = 0
    ledger = {}

    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    log_structured(correlation_id, "batch_started", "success")

    # Pre-define output file paths to prevent UnboundLocalError
    project_root = os.getcwd()
    output_folder = os.path.join(project_root, 'data', 'output')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    try:
        raw_folder = os.path.join(project_root, 'data', 'raw')
        ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
        ensure_folder(output_folder)

        input_file = os.path.join(raw_folder, 'toSequence.txt')
        if not os.path.isfile(input_file):
            # If no file exists, raise InputReadError
            log_structured(correlation_id, "file_check", "error", outcome_detail=f"Input file not found: {input_file}")
            raise InputReadError(f"Input file not found: {input_file}")

        # Instantiate calculator
        try:
            calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
        except Exception as e:
            log_structured(correlation_id, "rule_load", "error", outcome_detail=str(e))
            raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

        # Read DNA strings (canonical name: dna_sequence_list)
        try:
            dna_sequence_list = read_input_file(input_file)
        except Exception as e:
            log_structured(correlation_id, "input_read", "error", outcome_detail=str(e))
            raise InputReadError(f"Failed to read input file: {input_file}") from e

        try:
            ledger = load_ledger(ledger_path)
        except Exception as e:
            log_structured(correlation_id, "ledger_load", "error", outcome_detail=str(e))
            raise

        if not dna_sequence_list:
            latency = int((time.time() - start_time) * 1000)
            log_structured(correlation_id, "batch_completed", "no_new_items", latency_ms=latency)
            return BatchResult("NO_NEW_ITEMS", 0, len(ledger))

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

        for dna_sequence in dna_sequence_list:
            idempotency_key = dna_sequence
            if idempotency_key in ledger:
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
                outcome = DNAStatus.SUCCESS

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
                outcome = DNAStatus.ERROR

            # Update ledger inside the loop
            ledger[idempotency_key] = {
                'terminal_outcome': outcome.value,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            new_processed_count += 1

            # Log item processing
            log_structured(
                correlation_id=correlation_id,
                step="process_sequence",
                outcome=outcome.value,
                idempotency_key=idempotency_key,
                outcome_detail="Parsed successfully" if outcome == DNAStatus.SUCCESS else "Failed parsing"
            )

        # Write output files & ledger if there are new processed items
        if new_processed_count > 0:
            # ATOMIC WRITE PATTERN:
            # 1. Write to a temporary directory in the same filesystem as the output folder
            # 2. Flush and sync files to ensure they are on disk
            # 3. Rename them to their final destination (atomic on most OSes)
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

                try:
                    # Write JSON output to temp
                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    # Write CSV output to temp
                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())

                    # Atomic rename (commit)
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

                except Exception as e:
                    log_structured(correlation_id, "atomic_write", "error", outcome_detail=str(e))
                    raise AtomicWriteError("Failed to write output files atomically") from e

            # Save ledger atomically
            save_ledger(ledger_path, ledger)

    except Exception as e:
        error_occurred = True
        raise e

    finally:
        latency = int((time.time() - start_time) * 1000)
        status = "SUCCESS" if (new_processed_count > 0 and not error_occurred) else ("no_new_items" if not error_occurred else "error")
        log_structured(correlation_id, "batch_completed", status.lower(), latency_ms=latency)

    status_str = "SUCCESS" if new_processed_count > 0 else "NO_NEW_ITEMS"
    return BatchResult(status_str, new_processed_count, len(ledger))

# Maintain backwards compatibility for main.py & tests
main = run_batch

if __name__ == '__main__':
    run_batch()
