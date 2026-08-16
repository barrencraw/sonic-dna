#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import datetime
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input DNA files fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when ledger persistence fails."""
    pass

def log_structured(correlation_id, chain_name, step, outcome, latency_ms, actor_id, idempotency_key=None, outcome_detail=None):
    payload = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "system",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 3) if latency_ms is not None else 0.0,
        "idempotency_key": idempotency_key or "",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(payload)}")
    return payload

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
        return dna_sequence_list
    except Exception as e:
        raise InputReadError(f"Failed to read input file '{input_path}': {e}") from e

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

def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    chain_name = "dna_batch_parse"
    corr_id = correlation_id or str(uuid.uuid4())

    log_structured(
        correlation_id=corr_id,
        chain_name=chain_name,
        step="batch_start",
        outcome="started",
        latency_ms=0.0,
        actor_id=actor_id
    )

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=corr_id,
            chain_name=chain_name,
            step="check_input_file",
            outcome=DNAStatus.SKIPPED.value,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            correlation_id=corr_id,
            chain_name=chain_name,
            step="load_rules",
            outcome=DNAStatus.ERROR.value,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            outcome_detail=f"Rule load failure: {e}"
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        log_structured(
            correlation_id=corr_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.SKIPPED.value,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            outcome_detail="No DNA sequences found in toSequence.txt"
        )
        return

    ledger = load_ledger(ledger_path)

    # Load existing JSON output
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

    # Load existing CSV rows
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
        seq_start = time.time()

        if idempotency_key in ledger:
            log_structured(
                correlation_id=corr_id,
                chain_name=chain_name,
                step="process_sequence",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=(time.time() - seq_start) * 1000,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit; previous outcome={ledger[idempotency_key].get('terminal_outcome')}"
            )
            continue

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,  # Backwards compatibility
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_sequence
            flat['dna'] = dna_sequence  # Backwards compatibility
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value
            outcome_detail = f"Rule={result['rule']}"

        except RuleParseError as e:
            parsed_json.append({
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,
                'error': str(e)
            })
            flat = {'dna_sequence': dna_sequence, 'dna': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value
            outcome_detail = f"Parse error: {e}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        new_processed_count += 1

        log_structured(
            correlation_id=corr_id,
            chain_name=chain_name,
            step="process_sequence",
            outcome=outcome,
            latency_ms=(time.time() - seq_start) * 1000,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                # 1) JSON output
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) CSV output
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Ledger output
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic rename
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                log_structured(
                    correlation_id=corr_id,
                    chain_name=chain_name,
                    step="atomic_persistence",
                    outcome=DNAStatus.ERROR.value,
                    latency_ms=(time.time() - start_time) * 1000,
                    actor_id=actor_id,
                    outcome_detail=f"Atomic write error: {e}"
                )
                raise PersistenceError("Failed to write output files atomically") from e

    log_structured(
        correlation_id=corr_id,
        chain_name=chain_name,
        step="batch_complete",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=(time.time() - start_time) * 1000,
        actor_id=actor_id,
        outcome_detail=f"Processed {new_processed_count} new sequences. Total ledger entries: {len(ledger)}"
    )

def main():
    run_batch()

if __name__ == '__main__':
    main()
