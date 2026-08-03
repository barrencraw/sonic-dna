#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing or moving output files atomically fails."""
    pass

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

def log_structured(step, outcome, correlation_id=None, actor_id="system", chain_name="dna_batch_parsing", latency_ms=0, idempotency_key=None, outcome_detail=None):
    """
    Standardized structured logging with prefix JSON_LOG:
    Mandatory fields: timestamp (UTC), correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, and outcome_detail.
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        'timestamp': now_utc,
        'correlation_id': correlation_id or "N/A",
        'actor_id': actor_id,
        'chain_name': chain_name,
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key or "N/A",
        'outcome_detail': outcome_detail or ""
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads inputs; each line is one DNA sequence.
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    # Ensure folder exists
    ledger_dir = os.path.dirname(ledger_path)
    ensure_folder(ledger_dir)

    # Atomic write pattern for ledger
    tmp_file = None
    try:
        # Create temp file in the same directory as the ledger
        fd, tmp_path = tempfile.mkstemp(dir=ledger_dir, suffix='.tmp')
        tmp_file = os.fdopen(fd, 'w', encoding='utf-8')
        json.dump(ledger, tmp_file, indent=2)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
        tmp_file.close()
        tmp_file = None # Avoid double closing in finally

        # Atomic rename
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        # Clean up temporary file if it was created
        if tmp_file:
            try:
                tmp_file.close()
            except Exception:
                pass
        try:
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise LedgerSaveError(f"Failed to save ledger atomically: {e}") from e

def run_batch(correlation_id=None):
    start_time = time.time()
    # Pre-define output file paths to avoid UnboundLocalError
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    log_structured(
        step="start",
        outcome="processing",
        correlation_id=correlation_id,
        idempotency_key=None,
        outcome_detail="Starting batch DNA parsing"
    )

    error_occurred = False
    new_processed_count = 0

    try:
        if not os.path.isfile(input_file):
            log_structured(
                step="input_validation",
                outcome="error",
                correlation_id=correlation_id,
                outcome_detail=f"Input file not found: {input_file}"
            )
            return

        # Instantiate calculator
        try:
            calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
        except Exception as e:
            error_occurred = True
            raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

        # Read DNA strings
        try:
            dna_sequence_list = read_input_file(input_file)
        except Exception as e:
            error_occurred = True
            raise InputReadError(f"Failed to read input file: {input_file}") from e

        if not dna_sequence_list:
            log_structured(
                step="read_input",
                outcome="success",
                correlation_id=correlation_id,
                outcome_detail="No DNA strings found in toSequence.txt"
            )
            return

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

        for dna_sequence in dna_sequence_list:
            idempotency_key = dna_sequence

            # Support .get('ledger', ledger) or just ledger directly for legacy/modern structure
            ledger_data = ledger.get('ledger', ledger)
            if idempotency_key in ledger_data:
                outcome_status = ledger_data[idempotency_key].get('terminal_outcome')
                log_structured(
                    step="idempotency_check",
                    outcome="skipped",
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Dedupe hit. Already processed with status: {outcome_status}"
                )
                continue

            # Process
            step_start = time.time()
            try:
                result = calculator.parse(dna_sequence)
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

                outcome_status = DNAStatus.SUCCESS.value
                outcome_detail = "Successfully parsed DNA sequence"

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

                outcome_status = DNAStatus.ERROR.value
                outcome_detail = f"Parse error: {str(e)}"

            # Update ledger inside loop for idempotency per sequence
            timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            ledger_data[idempotency_key] = {
                'terminal_outcome': outcome_status,
                'timestamp': timestamp
            }
            if 'ledger' in ledger:
                ledger['ledger'] = ledger_data
            else:
                ledger = ledger_data

            latency = int((time.time() - step_start) * 1000)
            log_structured(
                step="parse_sequence",
                outcome=outcome_status,
                correlation_id=correlation_id,
                latency_ms=latency,
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail
            )
            new_processed_count += 1

        # Save ledger and write output files if we processed anything new
        if new_processed_count > 0:
            # Save ledger atomically
            save_ledger(ledger_path, ledger)

            # Atomic Write Pattern for CSV & JSON
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
                    if 'dna_sequence' in fieldnames:
                        fieldnames.remove('dna_sequence')
                        fieldnames = ['dna_sequence'] + fieldnames

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
                    error_occurred = True
                    raise AtomicWriteError("Failed to write output files atomically") from e

        log_structured(
            step="end",
            outcome="success",
            correlation_id=correlation_id,
            latency_ms=int((time.time() - start_time) * 1000),
            outcome_detail=f"Processed {new_processed_count} new DNA strings."
        )

    except Exception as e:
        error_occurred = True
        log_structured(
            step="end",
            outcome="error",
            correlation_id=correlation_id,
            latency_ms=int((time.time() - start_time) * 1000),
            outcome_detail=f"Batch execution failed: {str(e)}"
        )
        raise e

    finally:
        try:
            pass
        except Exception as cleanup_err:
            log_structured(
                step="cleanup_failure",
                outcome="error",
                correlation_id=correlation_id,
                outcome_detail=f"Cleanup failed: {str(cleanup_err)}"
            )
            if not error_occurred:
                raise cleanup_err

# Alias for backwards compatibility
main = run_batch
