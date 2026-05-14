#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from utils.dna_calculator import DNACalculator, RuleParseError

class TerminalOutcome(Enum):
    SUCCESS = "success"
    PARSE_ERROR = "error"
    SKIPPED = "skipped"

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
    dna_list = []
    if not os.path.exists(input_path):
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

import uuid

def log_structured(correlation_id: str, step: str, outcome: str, latency_ms: Optional[int] = None, actor_id: Optional[str] = None, **kwargs):
    log_entry = {
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "actor_id": actor_id,
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    log_entry.update(kwargs)
    print(json.dumps(log_entry))

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to save ledger: {e}")

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    correlation_id = str(uuid.uuid4())
    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, "file_check", "error", error="Input file not found")
        return

    # Instantiate calculator
    try:
        start_time = time.time()
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
        latency = int((time.time() - start_time) * 1000)
        log_structured(correlation_id, "load_rules", "success", latency_ms=latency)
    except Exception as e:
        log_structured(correlation_id, "load_rules", "error", error=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, "read_input", "error", error=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)

    # Load existing outputs to append to them
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
    for dna_sequence in dna_list:
        start_time_seq = time.time()
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(correlation_id, "parsing", "skipped", idempotency_key=idempotency_key, dedupe_hit=True)
            continue

        try:
            result = calculator.parse(idempotency_key)
            entry = {
                'dna': idempotency_key,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = idempotency_key
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = TerminalOutcome.SUCCESS
            error_msg = None

        except RuleParseError as e:
            outcome = TerminalOutcome.PARSE_ERROR
            error_msg = str(e)
            parsed_json.append({
                'dna': idempotency_key,
                'error': error_msg
            })
            flat = {'dna': idempotency_key, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        latency_seq = int((time.time() - start_time_seq) * 1000)
        log_structured(correlation_id, "parsing", outcome.value, latency_ms=latency_seq, idempotency_key=idempotency_key)

        # Update ledger
        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
        start_time_write = time.time()
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
                save_ledger(ledger_path, ledger)
                latency_write = int((time.time() - start_time_write) * 1000)
                log_structured(correlation_id, "atomic_write", "success", latency_ms=latency_write)

            except Exception as e:
                log_structured(correlation_id, "atomic_write", "error", error=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    log_structured(correlation_id, "batch_process", "success", processed_count=new_processed_count, total_ledger=len(ledger))
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
