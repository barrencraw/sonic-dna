#!/usr/bin/env python3
import os
import json
import csv
import time
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from utils.dna_calculator import DNACalculator, RuleParseError

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequences = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_sequences.append(s)
    return dna_sequences

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

class TerminalOutcome(Enum):
    SUCCESS = "success"
    PARSE_ERROR = "parse_error"
    SKIPPED = "skipped"

@dataclass
class DNAProcessingResult:
    dna_sequence: str
    outcome: TerminalOutcome
    rule: Optional[str] = None
    parsed_values: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

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

def log_structured(step, outcome, latency_ms=None, correlation_id=None, idempotency_key=None, actor_id='system', chain_name='dna_batch_chain'):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key
    }
    print(json.dumps(log_entry))

def main():
    start_time = time.time()
    correlation_id = f"batch_{int(start_time)}"
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured("check_input", "not_found", correlation_id=correlation_id)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequences = read_input_file(input_file)
    except Exception as e:
        log_structured("read_input", "error", correlation_id=correlation_id)
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequences:
        log_structured("read_input", "empty", correlation_id=correlation_id)
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

    from utils.dna_calculator import RuleParseError

    new_processed_count = 0
    for dna_sequence in dna_sequences:
        item_start = time.time()
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured("parse_sequence", "skipped", correlation_id=correlation_id, idempotency_key=idempotency_key)
            continue

        processing_result: DNAProcessingResult
        try:
            parsed = calculator.parse(dna_sequence)
            processing_result = DNAProcessingResult(
                dna_sequence=dna_sequence,
                outcome=TerminalOutcome.SUCCESS,
                rule=parsed['rule'],
                parsed_values=parsed['values']
            )
        except RuleParseError as e:
            processing_result = DNAProcessingResult(
                dna_sequence=dna_sequence,
                outcome=TerminalOutcome.PARSE_ERROR,
                error_message=str(e)
            )

        if processing_result.outcome == TerminalOutcome.SUCCESS:
            entry = {
                'dna': processing_result.dna_sequence,
                'rule': processing_result.rule,
                'parsed': processing_result.parsed_values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(processing_result.rule, processing_result.parsed_values)
            flat['dna'] = processing_result.dna_sequence
            flat['rule'] = processing_result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = TerminalOutcome.SUCCESS.value

        elif processing_result.outcome == TerminalOutcome.PARSE_ERROR:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': processing_result.dna_sequence,
                'error': processing_result.error_message
            })
            # Also put a row in CSV listing error
            flat = {'dna': processing_result.dna_sequence, 'error': processing_result.error_message}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = TerminalOutcome.PARSE_ERROR.value

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        latency = int((time.time() - item_start) * 1000)
        log_structured("parse_sequence", outcome, latency_ms=latency, correlation_id=correlation_id, idempotency_key=idempotency_key)
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    if new_processed_count > 0:
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

                # 4) Save ledger
                save_ledger(ledger_path, ledger)

            except Exception as e:
                log_structured("atomic_commit", "failed", correlation_id=correlation_id)
                raise PersistenceError("Failed to write output files atomically") from e

    total_latency = int((time.time() - start_time) * 1000)
    log_structured("batch_complete", "success", latency_ms=total_latency, correlation_id=correlation_id)

if __name__ == '__main__':
    main()
