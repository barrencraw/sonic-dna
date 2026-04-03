#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from dataclasses import asdict
from utils.dna_calculator import DNACalculator, RuleParseError, ProcessingResult, ParsedDNA

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if not os.path.isfile(input_path):
        return dna_list
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

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

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class Outcome(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    NO_NEW_DNA = "no_new_dna"

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def log_observability(
    correlation_id: str,
    chain_name: str,
    step: str,
    outcome: str,
    latency_ms: float,
    actor_id: str = "system",
    idempotency_key: str = None,
    error_message: str = None
):
    log_data = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
    }
    if idempotency_key:
        log_data["idempotency_key"] = idempotency_key
    if error_message:
        log_data["error_message"] = error_message

    print(f"[OBSERVABILITY] {json.dumps(log_data)}")

def main(correlation_id: str = None, actor_id: str = "system"):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    start_time = time.time()
    chain_name = "dna_batch_chain"

    log_observability(
        correlation_id=correlation_id,
        chain_name=chain_name,
        step="START",
        outcome=Outcome.SUCCESS.value,
        latency_ms=0,
        actor_id=actor_id
    )

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

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        latency = (time.time() - start_time) * 1000
        log_observability(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="END",
            outcome=Outcome.NO_NEW_DNA.value,
            latency_ms=latency,
            actor_id=actor_id
        )
        return

    ledger = load_ledger(ledger_path)

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                data = json.load(jf)
                if isinstance(data, list):
                    parsed_json = data
        except Exception:
            pass

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
    for dna_str in dna_list:
        dna_start_time = time.time()
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability(
                correlation_id=correlation_id,
                chain_name=chain_name,
                step="IDEMPOTENCY_CHECK",
                outcome=Outcome.SKIPPED.value,
                latency_ms=(time.time() - dna_start_time) * 1000,
                actor_id=actor_id,
                idempotency_key=idempotency_key
            )
            continue

        try:
            parsed_dna = calculator.parse(dna_str)

            entry = {
                'dna': dna_str,
                'rule': parsed_dna.rule,
                'parsed': parsed_dna.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(parsed_dna.rule, parsed_dna.values)
            flat['dna'] = dna_str
            flat['rule'] = parsed_dna.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS.value
            error_msg = None

        except RuleParseError as e:
            error_msg = str(e)
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': error_msg
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR.value

        log_observability(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="PARSE_DNA",
            outcome=outcome,
            latency_ms=(time.time() - dna_start_time) * 1000,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            error_message=error_msg
        )

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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

                # 3) Write Ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                raise PersistenceError(f"Failed to write output files atomically: {e}") from e

    latency = (time.time() - start_time) * 1000
    log_observability(
        correlation_id=correlation_id,
        chain_name=chain_name,
        step="END",
        outcome=Outcome.SUCCESS.value,
        latency_ms=latency,
        actor_id=actor_id
    )

if __name__ == '__main__':
    main()
