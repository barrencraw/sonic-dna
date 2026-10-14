#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

    def __str__(self):
        return self.value

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
    """Raised when writing or moving output/ledger files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when ledger loading fails due to corruption."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal limits are exceeded."""
    pass

def log_structured(chain_name, step, outcome, correlation_id=None, actor_id=None, latency_ms=0, idempotency_key=None, outcome_detail=None):
    """
    Standardized structured logging emitter prefixed with JSON_LOG:
    """
    timestamp_utc = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        "timestamp": timestamp_utc,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name,
        "step": step,
        "outcome": str(outcome),
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
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequence_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequence_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_path}") from e
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
            raise LedgerLoadError(f"Failed to load ledger at {ledger_path}: {e}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        folder = os.path.dirname(ledger_path)
        if folder:
            ensure_folder(folder)
        with tempfile.NamedTemporaryFile('w', dir=folder if folder else '.', delete=False, encoding='utf-8') as tf:
            json.dump(ledger, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_name = tf.name
        os.replace(tmp_name, ledger_path)
    except Exception as e:
        if 'tmp_name' in locals() and os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            chain_name="dna_batch_parser",
            step="input_check",
            outcome=DNAStatus.SKIPPED,
            correlation_id=correlation_id,
            actor_id=actor_id,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        log_structured(
            chain_name="dna_batch_parser",
            step="input_check",
            outcome=DNAStatus.SKIPPED,
            correlation_id=correlation_id,
            actor_id=actor_id,
            outcome_detail="No DNA sequences found in input file"
        )
        return

    ledger = load_ledger(ledger_path)

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
        except Exception:
            parsed_json = []

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
        chain_name="dna_batch_parser",
        step="batch_start",
        outcome=DNAStatus.SUCCESS,
        correlation_id=correlation_id,
        actor_id=actor_id,
        outcome_detail=f"Starting batch parse for {len(dna_sequence_list)} sequence(s)"
    )

    new_processed_count = 0
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(
                chain_name="dna_batch_parser",
                step="dedupe_check",
                outcome=DNAStatus.SKIPPED,
                correlation_id=correlation_id,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit, status={ledger[idempotency_key].get('terminal_outcome')}"
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

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

        ledger[idempotency_key] = {
            'terminal_outcome': str(outcome),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    if new_processed_count > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            try:
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
                raise AtomicWriteError("Failed to write output files atomically") from e

        save_ledger(ledger_path, ledger)

    latency_ms = int((time.time() - start_time) * 1000)
    log_structured(
        chain_name="dna_batch_parser",
        step="batch_completed",
        outcome=DNAStatus.SUCCESS,
        correlation_id=correlation_id,
        actor_id=actor_id,
        latency_ms=latency_ms,
        outcome_detail=f"Processed {new_processed_count} new sequence(s)"
    )

main = run_batch

if __name__ == '__main__':
    main()
