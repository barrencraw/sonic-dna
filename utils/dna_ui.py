#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from dataclasses import dataclass, asdict
from typing import Optional, Any, Dict
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"

@dataclass
class ParsedDNA:
    dna: str
    rule: Optional[str] = None
    values: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    outcome: Outcome = Outcome.SUCCESS

    def to_dict(self):
        d = asdict(self)
        d['outcome'] = self.outcome.value
        return d

def log_observability(correlation_id: str, chain_name: str, step: str, outcome: str,
                      latency_ms: Optional[float] = None, actor_id: str = "dna_ui",
                      idempotency_key: Optional[str] = None, data: Optional[dict] = None):
    """
    Standardized structured logging for SonicDNA.
    Grep Recipe: grep "| TELEMETRY |" <log_file> | jq '.data'
    """
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.upper(),
        "latency_ms": latency_ms,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
        "data": data or {}
    }
    print(f"| TELEMETRY | {json.dumps(log_entry)}")

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
    if not values_dict:
        return items
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

def main(data_dir=None):
    correlation_id = str(uuid.uuid4())
    start_time = time.time()
    log_observability(correlation_id, "dna_batch_chain", "START", Outcome.SUCCESS.value)

    # Determine file paths
    project_root = data_dir or os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(correlation_id, "dna_batch_chain", "INPUT_CHECK", Outcome.ERROR.value, data={"reason": "Input file not found"})
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, "dna_batch_chain", "INIT", Outcome.ERROR.value, data={"error": str(e)})
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(correlation_id, "dna_batch_chain", "READ", Outcome.ERROR.value, data={"error": str(e)})
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(correlation_id, "dna_batch_chain", "BATCH_EMPTY", Outcome.SUCCESS.value)
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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_observability(correlation_id, "dna_batch_chain", "IDEMPOTENCY_CHECK", Outcome.SKIPPED.value,
                              idempotency_key=idempotency_key, data={"dedupe_hit": True})
            continue

        try:
            result = calculator.parse(dna_str)
            parsed_obj = ParsedDNA(dna=dna_str, rule=result['rule'], values=result['values'], outcome=Outcome.SUCCESS)
            parsed_json.append(parsed_obj.to_dict())

            # Flatten for CSV
            flat = flatten_parsed(parsed_obj.rule, parsed_obj.values)
            flat['dna'] = dna_str
            flat['rule'] = parsed_obj.rule
            flat['outcome'] = Outcome.SUCCESS.value
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome_val = Outcome.SUCCESS.value
            log_observability(correlation_id, "dna_batch_chain", "PROCESS", Outcome.SUCCESS.value, idempotency_key=idempotency_key)

        except RuleParseError as e:
            parsed_obj = ParsedDNA(dna=dna_str, error=str(e), outcome=Outcome.ERROR)
            parsed_json.append(parsed_obj.to_dict())

            flat = {'dna': dna_str, 'error': str(e), 'outcome': Outcome.ERROR.value}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome_val = Outcome.ERROR.value
            log_observability(correlation_id, "dna_batch_chain", "PROCESS", Outcome.ERROR.value, idempotency_key=idempotency_key, data={"error": str(e)})

        ledger[idempotency_key] = {
            'terminal_outcome': outcome_val,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
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

                # Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                log_observability(correlation_id, "dna_batch_chain", "PERSIST", Outcome.ERROR.value, data={"error": str(e)})
                raise PersistenceError("Failed to write output files atomically") from e

    latency = (time.time() - start_time) * 1000
    log_observability(correlation_id, "dna_batch_chain", "END", Outcome.SUCCESS.value, latency_ms=latency, data={"processed": new_processed_count})

if __name__ == '__main__':
    main()
