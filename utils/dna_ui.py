#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
import datetime
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any

from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    START = "START"
    NO_NEW_DNA = "NO_NEW_DNA"
    WARN = "WARN"
    REFUSAL = "REFUSAL"

@dataclass
class ProcessingResult:
    dna: str
    outcome: Outcome
    rule: Optional[str] = None
    values: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    latency_ms: float = 0.0

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

def log_observability(correlation_id, actor_id, step, outcome, latency_ms=0.0, idempotency_key=None, error_msg=None):
    """
    Standardized structured logging for observability.
    """
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "system",
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key
    }
    if error_msg:
        log_entry["error"] = error_msg

    print(f"[OBSERVABILITY] {json.dumps(log_entry)}")

def process_dna_string(calculator: DNACalculator, dna_str: str) -> ProcessingResult:
    """
    Explicit terminal states + typed error classification.
    """
    start = time.time()
    try:
        result = calculator.parse(dna_str)
        latency = (time.time() - start) * 1000
        return ProcessingResult(
            dna=dna_str,
            outcome=Outcome.SUCCESS,
            rule=result['rule'],
            values=result['values'],
            latency_ms=latency
        )
    except RuleParseError as e:
        latency = (time.time() - start) * 1000
        return ProcessingResult(
            dna=dna_str,
            outcome=Outcome.ERROR,
            error=f"RULE_PARSE_ERROR: {str(e)}",
            latency_ms=latency
        )
    except Exception as e:
        latency = (time.time() - start) * 1000
        return ProcessingResult(
            dna=dna_str,
            outcome=Outcome.ERROR,
            error=f"UNEXPECTED_ERROR: {str(e)}",
            latency_ms=latency
        )

def main(correlation_id=None, actor_id=None):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())

    log_observability(correlation_id, actor_id, "batch_init", Outcome.START)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(correlation_id, actor_id, "input_check", Outcome.ERROR, error_msg=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, actor_id, "rule_load", Outcome.ERROR, error_msg=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(correlation_id, actor_id, "input_read", Outcome.ERROR, error_msg=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(correlation_id, actor_id, "batch_complete", Outcome.NO_NEW_DNA)
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
            log_observability(correlation_id, actor_id, "dna_process", Outcome.SKIPPED, idempotency_key=idempotency_key)
            continue

        res = process_dna_string(calculator, dna_str)

        if res.outcome == Outcome.SUCCESS:
            parsed_json.append({
                'dna': res.dna,
                'rule': res.rule,
                'parsed': res.values
            })
            flat = flatten_parsed(res.rule, res.values)
            flat['dna'] = res.dna
            flat['rule'] = res.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
        else:
            parsed_json.append({
                'dna': res.dna,
                'error': res.error
            })
            flat = {'dna': res.dna, 'error': res.error}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        # Update ledger for each processed string
        ledger[idempotency_key] = {
            'terminal_outcome': res.outcome.value,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        log_observability(
            correlation_id, actor_id, "dna_process", res.outcome,
            latency_ms=res.latency_ms, idempotency_key=idempotency_key,
            error_msg=res.error
        )
        new_processed_count += 1

    if new_processed_count == 0:
        log_observability(correlation_id, actor_id, "batch_complete", Outcome.NO_NEW_DNA, latency_ms=(time.time()-start_time)*1000)
        return

    # ATOMIC WRITE PATTERN:
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
            log_observability(correlation_id, actor_id, "persistence", Outcome.ERROR, error_msg=str(e))
            raise PersistenceError("Failed to write output files atomically") from e

    total_latency = (time.time() - start_time) * 1000
    log_observability(correlation_id, actor_id, "batch_complete", Outcome.SUCCESS, latency_ms=total_latency)

if __name__ == '__main__':
    main()
