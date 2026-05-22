#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from utils.dna_calculator import DNACalculator, RuleParseError

class TerminalOutcome(Enum):
    SUCCESS = "SUCCESS"
    PARSE_ERROR = "PARSE_ERROR"
    SKIPPED = "SKIPPED"

@dataclass
class DNAProcessingResult:
    dna_sequence: str
    terminal_outcome: TerminalOutcome
    rule: Optional[str] = None
    values: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def log_structured(correlation_id: str, chain_name: str, step: str, outcome_val: str,
                   idempotency_key: Optional[str] = None, latency_ms: Optional[float] = None,
                   actor_id: str = "batch_processor"):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome_val,
        "actor_id": actor_id
    }
    if idempotency_key:
        log_entry["idempotency_key"] = idempotency_key
    if latency_ms is not None:
        log_entry["latency_ms"] = latency_ms

    print(json.dumps(log_entry))

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

def main(correlation_id: Optional[str] = None):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    chain_name = "dna_batch_chain"
    start_time = time.time()

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
        log_structured(correlation_id, chain_name, "init", "failed", outcome_val="input_file_not_found")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, chain_name, "load_rules", "failed", outcome_val=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequences = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, chain_name, "read_input", "failed", outcome_val=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequences:
        log_structured(correlation_id, chain_name, "init", "success", outcome_val="no_sequences_found")
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
    for dna_sequence in dna_sequences:
        idempotency_key = dna_sequence
        seq_start_time = time.time()

        if idempotency_key in ledger:
            log_structured(correlation_id, chain_name, "process_sequence", outcome_val="skipped",
                           idempotency_key=idempotency_key)
            continue

        try:
            result = calculator.parse(dna_sequence)
            proc_result = DNAProcessingResult(
                dna_sequence=dna_sequence,
                terminal_outcome=TerminalOutcome.SUCCESS,
                rule=result['rule'],
                values=result['values']
            )

            entry = {
                'dna': proc_result.dna_sequence,
                'rule': proc_result.rule,
                'parsed': proc_result.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(proc_result.rule, proc_result.values)
            flat['dna'] = proc_result.dna_sequence
            flat['rule'] = proc_result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = proc_result.terminal_outcome

        except RuleParseError as e:
            # On parse error, record as error entry
            proc_result = DNAProcessingResult(
                dna_sequence=dna_sequence,
                terminal_outcome=TerminalOutcome.PARSE_ERROR,
                error_message=str(e)
            )
            parsed_json.append({
                'dna': proc_result.dna_sequence,
                'error': proc_result.error_message
            })
            # Also put a row in CSV listing error
            flat = {'dna': proc_result.dna_sequence, 'error': proc_result.error_message}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = proc_result.terminal_outcome

        latency_ms = (time.time() - seq_start_time) * 1000
        log_structured(correlation_id, chain_name, "process_sequence", outcome.value,
                       idempotency_key=idempotency_key, latency_ms=latency_ms)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
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
                log_structured(correlation_id, chain_name, "atomic_write", outcome_val="failed")
                raise PersistenceError("Failed to write output files atomically") from e

    total_latency_ms = (time.time() - start_time) * 1000
    log_structured(correlation_id, chain_name, "batch_complete", outcome_val="success",
                   latency_ms=total_latency_ms)

if __name__ == '__main__':
    main()
