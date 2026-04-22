#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import getpass
from datetime import datetime, timezone
from enum import Enum
from dataclasses import asdict
from utils.dna_calculator import DNACalculator, RuleParseError, ParsedDNA

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    NO_NEW_DNA = "NO_NEW_DNA"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"

def log_observability(chain_name, step, outcome, correlation_id=None, latency_ms=None, idempotency_key=None, extra=None):
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Enum) else outcome,
        "actor_id": getpass.getuser(),
    }
    if latency_ms is not None:
        log_entry["latency_ms"] = latency_ms
    if idempotency_key:
        log_entry["idempotency_key"] = idempotency_key
    if extra:
        log_entry.update(extra)

    # Pipe-delimited for easy grepping as per memory
    print(f"| {log_entry['timestamp']} | {log_entry['chain_name']} | {log_entry['step']} | {log_entry['outcome']} | {log_entry['correlation_id']} | {json.dumps(log_entry)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

def flatten_parsed(rule_name, values_dict, parent_key=''):
    items = {}
    for k, v in values_dict.items():
        new_key = f"{parent_key}.{k}" if parent_key else f"{rule_name}.{k}"
        if isinstance(v, dict):
            items.update(flatten_parsed(rule_name, v, new_key))
        else:
            items[new_key] = v
    return items

import tempfile
import shutil

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def main():
    start_time = time.time()
    correlation_id = str(uuid.uuid4())
    chain_name = "dna_batch_chain"

    log_observability(chain_name, "batch_init", Outcome.START, correlation_id=correlation_id)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(chain_name, "batch_init", Outcome.END, correlation_id=correlation_id, extra={"reason": "input_missing"})
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(chain_name, "rule_load", Outcome.ERROR, correlation_id=correlation_id, extra={"error": str(e)})
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(chain_name, "input_read", Outcome.ERROR, correlation_id=correlation_id, extra={"error": str(e)})
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(chain_name, "batch_init", Outcome.END, correlation_id=correlation_id, extra={"reason": "input_empty"})
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)

    # Load existing outputs to append
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
    success_count = 0
    error_count = 0

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability(chain_name, "process_item", Outcome.SKIPPED, correlation_id=correlation_id, idempotency_key=idempotency_key)
            continue

        log_observability(chain_name, "process_item", Outcome.PROCESSING, correlation_id=correlation_id, idempotency_key=idempotency_key)

        item_start = time.time()
        try:
            result = calculator.parse(dna_str) # Should return ParsedDNA
            entry = asdict(result)
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result.rule, result.values)
            flat['dna'] = result.dna
            flat['rule'] = result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = Outcome.SUCCESS
            success_count += 1

            ledger[idempotency_key] = {
                'terminal_outcome': outcome.value,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            outcome = Outcome.ERROR
            error_count += 1
            error_msg = str(e)

            parsed_json.append({
                'dna': dna_str,
                'error': error_msg
            })
            flat = {'dna': dna_str, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            ledger[idempotency_key] = {
                'terminal_outcome': outcome.value,
                'error': error_msg,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        latency_ms = (time.time() - item_start) * 1000
        log_observability(chain_name, "process_item", outcome, correlation_id=correlation_id, latency_ms=latency_ms, idempotency_key=idempotency_key)
        new_processed_count += 1

    if new_processed_count > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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

                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                log_observability(chain_name, "persistence", Outcome.ERROR, correlation_id=correlation_id, extra={"error": str(e)})
                raise PersistenceError("Failed to write output files atomically") from e

    final_outcome = Outcome.SUCCESS
    if success_count > 0 and error_count > 0:
        final_outcome = Outcome.PARTIAL_SUCCESS
    elif success_count == 0 and error_count > 0:
        final_outcome = Outcome.ERROR
    elif new_processed_count == 0:
        final_outcome = Outcome.NO_NEW_DNA

    latency_ms = (time.time() - start_time) * 1000
    log_observability(chain_name, "batch_complete", final_outcome, correlation_id=correlation_id, latency_ms=latency_ms, extra={"new_processed": new_processed_count})

    print(f"[{final_outcome.value}] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    if new_processed_count > 0:
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

if __name__ == '__main__':
    main()
