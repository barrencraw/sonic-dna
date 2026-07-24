#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail=None):
    """Emits JSON logs with the JSON_LOG: prefix."""
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "",
        "actor_id": actor_id or "system",
        "chain_name": chain_name or "dna_batch_parser",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(log_data)}", flush=True)

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

def process_single_dna(dna_sequence, calculator):
    """Encapsulates DNA string parsing to classify outcomes into explicit DNAStatus enum values."""
    try:
        result = calculator.parse(dna_sequence)
        # result is a dict with 'rule' and 'values'
        flat = flatten_parsed(result['rule'], result['values'])
        flat['dna'] = dna_sequence
        flat['rule'] = result['rule']
        return DNAStatus.SUCCESS, result, flat
    except RuleParseError as e:
        flat = {'dna': dna_sequence, 'error': str(e)}
        return DNAStatus.ERROR, str(e), flat

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    """The ledger file (processed_ledger.json) is saved atomically using a temp file write, flush, fsync, and replace."""
    ledger_dir = os.path.dirname(ledger_path)
    ensure_folder(ledger_dir)
    with tempfile.NamedTemporaryFile('w', dir=ledger_dir, delete=False, encoding='utf-8') as tf:
        json.dump(ledger, tf, indent=2)
        tf.flush()
        os.fsync(tf.fileno())
        temp_name = tf.name
    try:
        os.replace(temp_name, ledger_path)
    except Exception:
        if os.path.exists(temp_name):
            os.remove(temp_name)
        raise

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    actor_id = "system"
    chain_name = "dna_batch_parser"

    # Define output file paths once at the beginning of run_batch() to prevent UnboundLocalError and improve clarity
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    ensure_folder(output_folder)

    # Start log
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step="start",
        outcome="success",
        latency_ms=0,
        idempotency_key=None,
        outcome_detail="Batch processing started"
    )

    start_time = time.time()

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="input_check",
            outcome="skipped",
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="rule_load",
            outcome="error",
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail=f"Could not load rules: {str(e)}"
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="read_input",
            outcome="error",
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail=f"Failed to read input file: {str(e)}"
        )
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="process_batch",
            outcome="skipped",
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
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

    new_processed_count = 0
    error_occurred = False

    try:
        for dna_sequence in dna_sequence_list:
            idempotency_key = dna_sequence
            if idempotency_key in ledger:
                term_outcome = ledger[idempotency_key].get('terminal_outcome', '')
                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name=chain_name,
                    step="dedupe_hit",
                    outcome=term_outcome,
                    latency_ms=0,
                    idempotency_key=idempotency_key,
                    outcome_detail="Deduplication hit. Sequence already processed."
                )
                continue

            seq_start_time = time.time()
            status, result, flat = process_single_dna(dna_sequence, calculator)

            if status == DNAStatus.SUCCESS:
                entry = {
                    'dna': dna_sequence,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
            else:
                # status == DNAStatus.ERROR
                parsed_json.append({
                    'dna': dna_sequence,
                    'error': result
                })
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

            # Update ledger and new_processed_count inside the loop
            timestamp_utc = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            ledger[idempotency_key] = {
                'terminal_outcome': status.value,
                'timestamp': timestamp_utc
            }
            new_processed_count += 1

            latency_ms = int((time.time() - seq_start_time) * 1000)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step="process_single",
                outcome=status.value,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=None if status == DNAStatus.SUCCESS else f"Error: {result}"
            )

    except Exception as e:
        error_occurred = True
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="process_batch_loop",
            outcome="error",
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail=f"Exception in batch loop: {str(e)}"
        )
        raise

    finally:
        # Commit results if new_processed_count > 0, following atomic pattern
        if new_processed_count > 0:
            try:
                # Save ledger atomically first
                save_ledger(ledger_path, ledger)

                # Write JSON and CSV atomically
                with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                    tmp_json = os.path.join(tmp_dir, 'output.json')
                    tmp_csv = os.path.join(tmp_dir, 'output.csv')

                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())

                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                # If a persistence error occurs during cleanup, raise it only if no previous error occurred.
                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name=chain_name,
                    step="commit_results",
                    outcome="error",
                    latency_ms=int((time.time() - start_time) * 1000),
                    idempotency_key=None,
                    outcome_detail=f"Persistence error during write: {str(e)}"
                )
                if not error_occurred:
                    raise PersistenceError("Failed to write output files atomically") from e

    # End log
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step="end",
        outcome="success" if not error_occurred else "error",
        latency_ms=int((time.time() - start_time) * 1000),
        idempotency_key=None,
        outcome_detail=f"Batch processed. New: {new_processed_count}, total in ledger: {len(ledger)}"
    )

# Alias maintained for backward compatibility with imports
main = run_batch

if __name__ == '__main__':
    run_batch()
