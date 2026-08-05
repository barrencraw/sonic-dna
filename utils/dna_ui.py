#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class BatchResult:
    def __init__(self, status, processed_count, total_ledger_items):
        self.status = status                  # 'SUCCESS' or 'NO_NEW_ITEMS'
        self.processed_count = processed_count
        self.total_ledger_items = total_ledger_items

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when ledger saving fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

def log_structured(step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None, correlation_id=None):
    """
    Structured logging function.
    Emits JSON logs with the JSON_LOG: prefix.
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "",
        "actor_id": "system",
        "chain_name": "dna_batch_parsing",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

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
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    """
    Saves the ledger atomically via a temp file in the same directory.
    Guards against torn writes and ledger corruption.
    """
    ledger_dir = os.path.dirname(ledger_path)
    ensure_folder(ledger_dir)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=ledger_dir, prefix='.ledger_tmp')
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically: {e}") from e

def run_batch(correlation_id=None):
    # Establish UTC timestamp at start
    start_time = time.time()

    # Standardised path resolution
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    # Output paths defined once at the beginning
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            step="initialization",
            outcome="failed",
            outcome_detail=f"Input file not found: {input_file}",
            correlation_id=correlation_id
        )
        return BatchResult('NO_NEW_ITEMS', 0, 0)

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            step="rules_loading",
            outcome="failed",
            outcome_detail=f"Could not load rules: {e}",
            correlation_id=correlation_id
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings (canonical dna_sequence_list)
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            step="input_reading",
            outcome="failed",
            outcome_detail=f"Failed to read input file: {e}",
            correlation_id=correlation_id
        )
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    # Load existing ledger
    ledger = load_ledger(ledger_path)

    if not dna_sequence_list:
        log_structured(
            step="processing",
            outcome="skipped",
            outcome_detail="No DNA sequences found in input file",
            correlation_id=correlation_id
        )
        return BatchResult('NO_NEW_ITEMS', 0, len(ledger))

    log_structured(
        step="processing_start",
        outcome="success",
        outcome_detail=f"Processing batch of {len(dna_sequence_list)} items",
        correlation_id=correlation_id
    )

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
        for dna_sequence in dna_sequence_list:
            idempotency_key = dna_sequence
            if idempotency_key in ledger:
                log_structured(
                    step="deduplication",
                    outcome="skipped",
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Deduplication hit. Already processed with status {ledger[idempotency_key]['terminal_outcome']}",
                    correlation_id=correlation_id
                )
                continue

            item_start_time = time.time()
            try:
                result = calculator.parse(dna_sequence)
                # Use canonical key 'dna_sequence'
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

                outcome = DNAStatus.SUCCESS

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

                outcome = DNAStatus.ERROR

            # Update the ledger inside the iteration loop for each new sequence
            ledger[idempotency_key] = {
                'terminal_outcome': outcome.value,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }

            new_processed_count += 1
            latency_ms = int((time.time() - item_start_time) * 1000)

            log_structured(
                step="parse_item",
                outcome=outcome.value,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=f"Parsed sequence {dna_sequence}",
                correlation_id=correlation_id
            )

        # Post-loop file saving
        if new_processed_count > 0:
            # Atomic save of ledger
            save_ledger(ledger_path, ledger)

            # Atomic Write Pattern for JSON and CSV output
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
                    raise AtomicWriteError(f"Failed to write output files atomically: {e}") from e

    except Exception as e:
        error_occurred = True
        raise e

    finally:
        try:
            total_latency_ms = int((time.time() - start_time) * 1000)
            final_outcome = "success" if not error_occurred else "failed"
            log_structured(
                step="processing_end",
                outcome=final_outcome,
                latency_ms=total_latency_ms,
                outcome_detail=f"Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}",
                correlation_id=correlation_id
            )
        except Exception as cleanup_err:
            try:
                log_structured(
                    step="cleanup_failure",
                    outcome="failed",
                    outcome_detail=str(cleanup_err),
                    correlation_id=correlation_id
                )
            except Exception:
                pass
            if not error_occurred:
                raise cleanup_err

    status = 'SUCCESS' if new_processed_count > 0 else 'NO_NEW_ITEMS'
    return BatchResult(status, new_processed_count, len(ledger))

# Maintain alias for backwards compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
