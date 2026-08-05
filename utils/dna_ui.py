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

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
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

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class BatchResult:
    def __init__(self, status: str, processed_count: int, total_ledger_items: int):
        self.status = status  # 'SUCCESS' or 'NO_NEW_ITEMS'
        self.processed_count = processed_count
        self.total_ledger_items = total_ledger_items

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass

def log_structured(correlation_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail=None, actor_id="agent"):
    import datetime
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail or ""
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
    folder = os.path.dirname(ledger_path)
    ensure_folder(folder)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=folder, delete=False, encoding='utf-8') as tf:
            temp_name = tf.name
            json.dump(ledger, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(temp_name, ledger_path)
    except Exception as e:
        if temp_name and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically to {ledger_path}") from e

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())[:8]

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

    # Read DNA sequences
    if not os.path.isfile(input_file):
        ledger = load_ledger(ledger_path)
        return BatchResult('NO_NEW_ITEMS', 0, len(ledger))

    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    ledger = load_ledger(ledger_path)

    if not dna_sequence_list:
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

    new_processed_count = 0
    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        start_time = time.time()

        if idempotency_key in ledger:
            legacy_outcome = ledger[idempotency_key].get('terminal_outcome')
            latency_ms = int((time.time() - start_time) * 1000)
            log_structured(
                correlation_id=correlation_id,
                chain_name="dna_batch_parsing",
                step="idempotency_check",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplication hit. Legacy outcome: {legacy_outcome}"
            )
            continue

        try:
            result = calculator.parse(dna_seq)
            entry = {
                'dna_sequence': dna_seq,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_seq
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS

            latency_ms = int((time.time() - start_time) * 1000)
            log_structured(
                correlation_id=correlation_id,
                chain_name="dna_batch_parsing",
                step="parse_dna_sequence",
                outcome=outcome.value,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=f"Parsed rule: {result['rule']}"
            )

        except RuleParseError as e:
            # On parse error, record as error entry
            entry = {
                'dna_sequence': dna_seq,
                'error': str(e)
            }
            parsed_json.append(entry)

            # Also put a row in CSV listing error
            flat = {'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

            latency_ms = int((time.time() - start_time) * 1000)
            log_structured(
                correlation_id=correlation_id,
                chain_name="dna_batch_parsing",
                step="parse_dna_sequence",
                outcome=outcome.value,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=str(e)
            )

        # Update ledger inside the loop!
        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # Save ledger
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

    status = 'SUCCESS' if new_processed_count > 0 else 'NO_NEW_ITEMS'
    return BatchResult(status, new_processed_count, len(ledger))

# Maintain 'main' alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
