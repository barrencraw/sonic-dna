#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
import sys
from datetime import datetime, timezone
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
    """Raised when reading input DNA sequences fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing processed ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms=0.0, idempotency_key=None, outcome_detail=None):
    """
    Standardized structured logging emitter. Outputs JSON with prefix JSON_LOG:.
    """
    payload = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'correlation_id': correlation_id or str(uuid.uuid4()),
        'actor_id': actor_id or 'batch_parser',
        'chain_name': chain_name or 'dna_batch_parser',
        'step': step,
        'outcome': outcome,
        'latency_ms': round(latency_ms, 2),
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(payload)}")

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
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    chain_name = "dna_batch_parser"
    cid = correlation_id or str(uuid.uuid4())

    log_structured(
        correlation_id=cid,
        actor_id=actor_id,
        chain_name=chain_name,
        step="batch_start",
        outcome="started"
    )

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=cid,
            actor_id=actor_id,
            chain_name=chain_name,
            step="input_check",
            outcome=DNAStatus.REFUSED.value,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            correlation_id=cid,
            actor_id=actor_id,
            chain_name=chain_name,
            step="rules_load",
            outcome=DNAStatus.ERROR.value,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=str(e)
        )
        raise DNAProcessingError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        log_structured(
            correlation_id=cid,
            actor_id=actor_id,
            chain_name=chain_name,
            step="batch_end",
            outcome=DNAStatus.SKIPPED.value,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail="No DNA sequences found in input file"
        )
        return

    ledger = load_ledger(ledger_path)

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
        seq_start = time.time()
        idempotency_key = dna_seq

        if idempotency_key in ledger:
            log_structured(
                correlation_id=cid,
                actor_id=actor_id,
                chain_name=chain_name,
                step="parse_sequence",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=(time.time() - seq_start) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail="Deduplicated against ledger"
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

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_seq
            flat['dna_sequence'] = dna_seq
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value
            outcome_detail = f"Parsed rule '{result['rule']}'"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value
            outcome_detail = str(e)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        log_structured(
            correlation_id=cid,
            actor_id=actor_id,
            chain_name=chain_name,
            step="parse_sequence",
            outcome=outcome,
            latency_ms=(time.time() - seq_start) * 1000,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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
            log_structured(
                correlation_id=cid,
                actor_id=actor_id,
                chain_name=chain_name,
                step="atomic_write",
                outcome=DNAStatus.ERROR.value,
                latency_ms=(time.time() - start_time) * 1000,
                outcome_detail=f"Atomic write failed: {str(e)}"
            )
            raise AtomicWriteError("Failed to write output files atomically") from e

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger)

    log_structured(
        correlation_id=cid,
        actor_id=actor_id,
        chain_name=chain_name,
        step="batch_end",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=(time.time() - start_time) * 1000,
        outcome_detail=f"Processed {new_processed_count} new sequences. Total in ledger: {len(ledger)}"
    )

main = run_batch

if __name__ == '__main__':
    main()
