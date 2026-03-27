#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    START = "START"
    END = "END"
    NO_NEW_DNA = "NO_NEW_DNA"
    WARN = "WARN"

@dataclass
class ParsedDNA:
    """DTO for parsed DNA result."""
    dna: str
    rule: str
    values: Dict[str, Any]

@dataclass
class ProcessingResult:
    """Domain object for the outcome of a single DNA processing task."""
    dna: str
    outcome: Outcome
    parsed: Optional[ParsedDNA] = None
    error_msg: Optional[str] = None
    idempotency_key: Optional[str] = None
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
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

def log_obs(correlation_id: str, actor_id: str, step: str, outcome: Outcome,
            idempotency_key: str = None, latency_ms: float = 0.0, error_msg: str = None):
    """
    Standardized structured logging for observability.
    """
    log_data = {
        "correlation_id": correlation_id or "unknown",
        "actor_id": actor_id or "unknown",
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome.value,
        "latency_ms": round(latency_ms, 2),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    if idempotency_key:
        log_data["idempotency_key"] = idempotency_key
    if error_msg:
        log_data["error"] = error_msg

    print(f"[OBSERVABILITY] {json.dumps(log_data)}")

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
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def main(correlation_id=None, actor_id=None):
    log_obs(correlation_id, actor_id, "start_batch", Outcome.START)
    start_time = time.time()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        error_msg = f"Input file not found: {input_file}"
        log_obs(correlation_id, actor_id, "file_check", Outcome.ERROR, error_msg=error_msg)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_obs(correlation_id, actor_id, "load_rules", Outcome.ERROR, error_msg=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_obs(correlation_id, actor_id, "read_input", Outcome.ERROR, error_msg=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_obs(correlation_id, actor_id, "end_batch", Outcome.NO_NEW_DNA)
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
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_obs(correlation_id, actor_id, "dedupe_hit", Outcome.SKIPPED, idempotency_key=idempotency_key)
            continue

        item_start = time.time()

        try:
            parsed_data = calculator.parse(dna_str)
            dto = ParsedDNA(dna=dna_str, rule=parsed_data['rule'], values=parsed_data['values'])
            result = ProcessingResult(dna=dna_str, outcome=Outcome.SUCCESS, parsed=dto, idempotency_key=idempotency_key)

            entry = {
                'dna': dto.dna,
                'rule': dto.rule,
                'parsed': dto.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(dto.rule, dto.values)
            flat['dna'] = dto.dna
            flat['rule'] = dto.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        except RuleParseError as e:
            result = ProcessingResult(dna=dna_str, outcome=Outcome.ERROR, error_msg=str(e), idempotency_key=idempotency_key)
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        result.latency_ms = (time.time() - item_start) * 1000
        log_obs(correlation_id, actor_id, "process_dna", result.outcome,
                idempotency_key=result.idempotency_key, latency_ms=result.latency_ms, error_msg=result.error_msg)

        # Update ledger in memory
        ledger[idempotency_key] = {
            'terminal_outcome': result.outcome.value,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
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
                log_obs(correlation_id, actor_id, "atomic_write", Outcome.ERROR, error_msg=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    latency_ms = (time.time() - start_time) * 1000
    log_obs(correlation_id, actor_id, "end_batch", Outcome.END, latency_ms=latency_ms)

if __name__ == '__main__':
    main()
