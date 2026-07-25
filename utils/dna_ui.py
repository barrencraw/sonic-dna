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

class LedgerLoadError(DNAProcessingError):
    """Raised when ledger loading fails or is corrupted."""
    pass


def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequence_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            dna_sequence = line.strip()
            if dna_sequence:
                dna_sequence_list.append(dna_sequence)
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
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Ledger file is corrupted: {e}") from e
        except Exception as e:
            raise LedgerLoadError(f"Failed to read ledger file: {e}") from e
    return {}


def save_ledger(ledger_path, ledger):
    dir_name = os.path.dirname(ledger_path)
    ensure_folder(dir_name)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
            json.dump(ledger, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name
        os.replace(temp_name, ledger_path)
    except Exception as e:
        if temp_name and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except Exception:
                pass
        raise PersistenceError(f"Failed to save ledger atomically: {e}") from e


def log_structured(correlation_id, step, outcome, latency_ms=0, actor_id="system", idempotency_key=None, outcome_detail=None):
    # Precise ISO 8601 UTC timestamp format %Y-%m-%dT%H:%M:%SZ
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "system",
        "chain_name": "DNA Batch Parsing",
        "step": step,
        "outcome": outcome,
        "idempotency_key": idempotency_key or "N/A",
        "latency_ms": latency_ms,
        "outcome_detail": outcome_detail or "N/A"
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")


def run_batch(correlation_id=None):
    start_time = time.time()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, "batch_started", DNAStatus.SKIPPED.value, actor_id="system", outcome_detail=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, "rules_loading", DNAStatus.ERROR.value, actor_id="system", outcome_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, "input_reading", DNAStatus.ERROR.value, actor_id="system", outcome_detail=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        log_structured(correlation_id, "batch_started", DNAStatus.SKIPPED.value, actor_id="system", outcome_detail="No DNA sequences found in toSequence.txt")
        return

    # Start structured log
    log_structured(correlation_id, "batch_started", DNAStatus.SUCCESS.value, actor_id="system", outcome_detail=f"Found {len(dna_sequence_list)} DNA sequences.")

    try:
        ledger = load_ledger(ledger_path)
    except LedgerLoadError as e:
        log_structured(correlation_id, "ledger_loading", DNAStatus.ERROR.value, actor_id="system", outcome_detail=str(e))
        raise

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
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(
                correlation_id=correlation_id,
                step="deduplication",
                outcome=DNAStatus.SKIPPED.value,
                idempotency_key=idempotency_key,
                outcome_detail=ledger[idempotency_key]['terminal_outcome']
            )
            continue

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
            outcome = DNAStatus.SUCCESS.value
            outcome_detail = "Successfully parsed"

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
            outcome = DNAStatus.ERROR.value
            outcome_detail = str(e)

        # Precise ISO 8601 UTC timestamp format %Y-%m-%dT%H:%M:%SZ
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': timestamp
        }
        log_structured(
            correlation_id=correlation_id,
            step="process_sequence",
            outcome=outcome,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write ledger atomically
        save_ledger(ledger_path, ledger)

        # 2. Write JSON and CSV to a temporary directory in the same filesystem as the output folder
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
                log_structured(correlation_id, "output_saving", DNAStatus.ERROR.value, actor_id="system", outcome_detail=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    latency_ms = int((time.time() - start_time) * 1000)
    log_structured(
        correlation_id=correlation_id,
        step="batch_completed",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=latency_ms,
        actor_id="system",
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

# Alias maintained for backward compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
