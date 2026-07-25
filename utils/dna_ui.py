#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

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
    # Save ledger atomically using a temporary file in the same directory
    dir_name = os.path.dirname(ledger_path)
    with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
        json.dump(ledger, tf, indent=2)
        tf.flush()
        os.fsync(tf.fileno())
        temp_name = tf.name
    try:
        os.replace(temp_name, ledger_path)
    except Exception as e:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise e

def log_structured(step, outcome=None, latency_ms=0, idempotency_key=None, outcome_detail=None, correlation_id=None, actor_id='system'):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        'timestamp': timestamp,
        'correlation_id': correlation_id or 'unknown',
        'actor_id': actor_id,
        'chain_name': 'dna_batch_parsing',
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = 'unknown'

    # Determine file paths once at the beginning
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        print("[WARN] No DNA strings found in toSequence.txt")
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

    log_structured(
        step='start',
        outcome=DNAStatus.SUCCESS,
        correlation_id=correlation_id
    )

    new_processed_count = 0
    error_occurred = None

    try:
        for dna_sequence in dna_sequence_list:
            idempotency_key = dna_sequence
            # support flat ledger entries or potential nested dicts
            ledger_entry = ledger.get(idempotency_key)
            if ledger_entry:
                outcome_detail = ledger_entry.get('terminal_outcome') if isinstance(ledger_entry, dict) else str(ledger_entry)
                log_structured(
                    step='idempotency_skip',
                    outcome=DNAStatus.SKIPPED,
                    idempotency_key=idempotency_key,
                    outcome_detail=outcome_detail,
                    correlation_id=correlation_id
                )
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={outcome_detail}")
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            start_time = time.time()
            try:
                result = calculator.parse(dna_sequence)
                entry = {
                    'dna': dna_sequence,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_sequence
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.SUCCESS
                outcome_detail = 'Successfully parsed DNA sequence'

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_sequence,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna': dna_sequence, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR
                outcome_detail = str(e)

            latency_ms = int((time.time() - start_time) * 1000)

            # Record in ledger and update count inside the iteration!
            timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': timestamp
            }
            new_processed_count += 1

            log_structured(
                step='parse_dna',
                outcome=outcome,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail,
                correlation_id=correlation_id
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")

    except Exception as e:
        error_occurred = e
        log_structured(
            step='batch_error',
            outcome=DNAStatus.ERROR,
            outcome_detail=str(e),
            correlation_id=correlation_id
        )
        raise

    finally:
        # Save ledger and write output files if new items processed.
        # Ensure we write files atomically.
        if new_processed_count > 0:
            try:
                # Save ledger atomically
                save_ledger(ledger_path, ledger)

                # Write JSON and CSV outputs atomically
                with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                    tmp_json = os.path.join(tmp_dir, 'output.json')
                    tmp_csv = os.path.join(tmp_dir, 'output.csv')

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

                log_structured(
                    step='commit',
                    outcome=DNAStatus.SUCCESS,
                    correlation_id=correlation_id
                )

            except Exception as pe:
                log_structured(
                    step='commit',
                    outcome=DNAStatus.ERROR,
                    outcome_detail=str(pe),
                    correlation_id=correlation_id
                )
                if not error_occurred:
                    raise PersistenceError("Failed to write output files atomically") from pe

        log_structured(
            step='end',
            outcome=DNAStatus.ERROR if error_occurred else DNAStatus.SUCCESS,
            correlation_id=correlation_id
        )

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

# Maintain main as run_batch alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
