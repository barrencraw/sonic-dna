#!/usr/bin/env python3
import os
import json
import csv
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Any, Dict
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    START = 'start'
    END = 'end'

@dataclass
class ProcessingResult:
    outcome: Outcome
    data: Optional[Any] = None
    error_message: Optional[str] = None
    latency_ms: float = 0.0

def log_observability(correlation_id: str, actor_id: str, chain_name: str, step: str, outcome: Outcome, latency_ms: float = 0.0, idempotency_key: str = "N/A", error_message: Optional[str] = None):
    """
    Standardized structured logging for observability.
    """
    log_data = {
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
    }
    if error_message:
        log_data["error_message"] = error_message
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

def main(correlation_id: str = "N/A", actor_id: str = "N/A"):
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    chain_name = "dna_batch_chain"
    log_observability(correlation_id, actor_id, chain_name, "init", Outcome.START)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(correlation_id, actor_id, chain_name, "check_input", Outcome.ERROR, error_message=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, actor_id, chain_name, "load_rules", Outcome.ERROR, error_message=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(correlation_id, actor_id, chain_name, "read_input", Outcome.ERROR, error_message=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(correlation_id, actor_id, chain_name, "process_batch", Outcome.SKIPPED, error_message="No DNA strings found")
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

    from utils.dna_calculator import RuleParseError, ParsedDNA

    new_processed_count = 0
    for dna_str in dna_list:
        idempotency_key = dna_str
        start_time = time.time()

        if idempotency_key in ledger:
            log_observability(correlation_id, actor_id, chain_name, "idempotency_check", Outcome.SKIPPED, idempotency_key=idempotency_key)
            continue

        try:
            parsed_dna: ParsedDNA = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'rule': parsed_dna.rule_name,
                'parsed': parsed_dna.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(parsed_dna.rule_name, parsed_dna.values)
            flat['dna'] = dna_str
            flat['rule'] = parsed_dna.rule_name
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            processing_result = ProcessingResult(
                outcome=Outcome.SUCCESS,
                data=parsed_dna,
                latency_ms=(time.time() - start_time) * 1000
            )

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            processing_result = ProcessingResult(
                outcome=Outcome.ERROR,
                error_message=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )

        # Update ledger immediately after each DNA
        ledger[idempotency_key] = {
            'terminal_outcome': processing_result.outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_observability(correlation_id, actor_id, chain_name, "parse_dna", processing_result.outcome, latency_ms=processing_result.latency_ms, idempotency_key=idempotency_key)
        new_processed_count += 1

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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
                log_observability(correlation_id, actor_id, chain_name, "persist_results", Outcome.ERROR, error_message=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    log_observability(correlation_id, actor_id, chain_name, "batch_complete", Outcome.END)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
