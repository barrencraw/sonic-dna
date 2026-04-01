#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    START = "start"
    END = "end"

@dataclass
class ProcessingResult:
    dna: str
    outcome: Outcome
    rule: Optional[str] = None
    values: Optional[Dict[str, Any]] = None
    error_msg: Optional[str] = None

def log_observability(correlation_id: str, chain_name: str, step: str, outcome: Outcome,
                      latency_ms: int, actor_id: str, idempotency_key: str,
                      error_msg: Optional[str] = None):
    log_data = {
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value,
        "latency_ms": latency_ms,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
    }
    if error_msg:
        log_data["error"] = error_msg
    print(f"[OBSERVABILITY] {json.dumps(log_data)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
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

def main(correlation_id: str = None, actor_id: str = "system"):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    chain_name = "dna_batch_chain"
    start_time_batch = time.time()

    log_observability(correlation_id, chain_name, "batch_init", Outcome.START, 0, actor_id, "N/A")

    # Determine file paths
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
        log_observability(correlation_id, chain_name, "batch_end", Outcome.ERROR,
                          int((time.time() - start_time_batch) * 1000), actor_id, "N/A",
                          error_msg=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, chain_name, "rule_load", Outcome.ERROR,
                          int((time.time() - start_time_batch) * 1000), actor_id, "N/A",
                          error_msg=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(correlation_id, chain_name, "read_input", Outcome.ERROR,
                          int((time.time() - start_time_batch) * 1000), actor_id, "N/A",
                          error_msg=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        log_observability(correlation_id, chain_name, "batch_end", Outcome.SKIPPED,
                          int((time.time() - start_time_batch) * 1000), actor_id, "N/A")
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
    for dna_str in dna_list:
        start_time_dna = time.time()
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            log_observability(correlation_id, chain_name, "parse_dna", Outcome.SKIPPED,
                              int((time.time() - start_time_dna) * 1000), actor_id, idempotency_key)
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            parsed = calculator.parse(dna_str)
            res = ProcessingResult(
                dna=dna_str,
                outcome=Outcome.SUCCESS,
                rule=parsed['rule'],
                values=parsed['values']
            )
        except RuleParseError as e:
            res = ProcessingResult(
                dna=dna_str,
                outcome=Outcome.ERROR,
                error_msg=str(e)
            )

        if res.outcome == Outcome.SUCCESS:
            entry = {
                'dna': res.dna,
                'rule': res.rule,
                'parsed': res.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(res.rule, res.values)
            flat['dna'] = res.dna
            flat['rule'] = res.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
        else:
            # On parse error
            parsed_json.append({
                'dna': res.dna,
                'error': res.error_msg
            })
            # Also put a row in CSV listing error
            flat = {'dna': res.dna, 'error': res.error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        log_observability(correlation_id, chain_name, "parse_dna", res.outcome,
                          int((time.time() - start_time_dna) * 1000), actor_id, idempotency_key,
                          error_msg=res.error_msg)

        ledger[idempotency_key] = {
            'terminal_outcome': res.outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={res.outcome.value}")
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)

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
                log_observability(correlation_id, chain_name, "persistence", Outcome.ERROR,
                                  int((time.time() - start_time_batch) * 1000), actor_id, "N/A",
                                  error_msg=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    latency_total = int((time.time() - start_time_batch) * 1000)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    log_observability(correlation_id, chain_name, "batch_end", Outcome.END,
                      latency_total, actor_id, "N/A")

if __name__ == '__main__':
    main()
