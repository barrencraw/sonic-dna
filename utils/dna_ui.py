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

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input DNA file cannot be found or read."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence failures."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing the ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files fails atomically."""
    pass

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key=None, outcome_detail=None):
    outcome_str = outcome.value if hasattr(outcome, 'value') else str(outcome)
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome_str,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail or {}
    }
    print(f"JSON_LOG:{json.dumps(log_entry)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    if not os.path.isfile(input_path):
        raise InputReadError(f"Input file not found: {input_path}")
    dna_sequence_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequence_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file {input_path}: {e}") from e
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
                content = json.load(f)
                return content
        except Exception as e:
            raise LedgerLoadError(f"Ledger file at {ledger_path} is corrupted or unreadable.") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None, actor_id='batch_parser'):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())
    chain_name = 'dna_batch_processing'

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Read DNA sequences
    try:
        dna_sequence_list = read_input_file(input_file)
    except InputReadError as e:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step='read_input',
            outcome=DNAStatus.ERROR,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail={'error': str(e)}
        )
        raise

    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step='read_input',
            outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail={'message': 'No DNA sequences found in input file'}
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

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
    for dna_seq in dna_sequence_list:
        seq_start = time.time()
        idempotency_key = dna_seq
        if idempotency_key in ledger:
            terminal_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step='check_idempotency',
                outcome=DNAStatus.SKIPPED,
                latency_ms=(time.time() - seq_start) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail={'dedupe_hit': True, 'terminal_outcome': terminal_outcome}
            )
            continue

        try:
            result = calculator.parse(dna_seq)
            entry = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_seq
            flat['dna_sequence'] = dna_seq
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS
            outcome_detail = {'rule': result['rule']}

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR
            outcome_detail = {'error': str(e)}

        outcome_str = outcome.value if hasattr(outcome, 'value') else str(outcome)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome_str,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step='parse_sequence',
            outcome=outcome,
            latency_ms=(time.time() - seq_start) * 1000,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger)

        # Atomic write of JSON and CSV outputs
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

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step='batch_complete',
        outcome=DNAStatus.SUCCESS,
        latency_ms=(time.time() - start_time) * 1000,
        outcome_detail={
            'processed_count': new_processed_count,
            'total_ledger': len(ledger),
            'json_output': json_output_path,
            'csv_output': csv_output_path
        }
    )

main = run_batch

if __name__ == '__main__':
    run_batch()
