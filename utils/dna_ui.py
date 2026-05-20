#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
from enum import Enum
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
from utils.dna_calculator import DNACalculator, RuleParseError

class TerminalOutcome(Enum):
    SUCCESS = "SUCCESS"
    PARSE_ERROR = "PARSE_ERROR"
    SKIPPED = "SKIPPED"

@dataclass
class DNAProcessingResult:
    dna_sequence: str
    terminal_outcome: TerminalOutcome
    parsed_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    latency_ms: float = 0.0

def log_structured(correlation_id: str, chain_name: str, step: str, outcome: str,
                   latency_ms: Optional[float] = None, actor_id: Optional[str] = None,
                   idempotency_key: Optional[str] = None, extra: Optional[Dict[str, Any]] = None):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
    }
    if latency_ms is not None:
        log_entry["latency_ms"] = f"{latency_ms:.2f}"
    if actor_id:
        log_entry["actor_id"] = actor_id
    if idempotency_key:
        log_entry["idempotency_key"] = idempotency_key
    if extra:
        log_entry.update(extra)

    print(json.dumps(log_entry))

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
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
    correlation_id = str(uuid.uuid4())
    chain_name = "dna_batch_chain"
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, chain_name, "init", "ERROR", extra={"message": f"Input file not found: {input_file}"})
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, chain_name, "init", "ERROR", extra={"message": f"Could not load rules: {str(e)}"})
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_sequences = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequences:
        log_structured(correlation_id, chain_name, "read_input", "SKIPPED", extra={"message": "No DNA sequences found"})
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
    results: List[DNAProcessingResult] = []

    for dna_sequence in dna_sequences:
        idempotency_key = dna_sequence
        start_time = time.time()

        if idempotency_key in ledger:
            log_structured(correlation_id, chain_name, "process_item", "SKIPPED",
                           idempotency_key=idempotency_key,
                           extra={"dedupe_hit": True, "terminal_outcome": ledger[idempotency_key]['terminal_outcome']})
            continue

        log_structured(correlation_id, chain_name, "process_item", "STARTING", idempotency_key=idempotency_key)

        try:
            parse_result = calculator.parse(dna_sequence)
            outcome = TerminalOutcome.SUCCESS
            error_msg = None
            parsed_data = parse_result

            entry = {
                'dna': dna_sequence,
                'rule': parse_result['rule'],
                'parsed': parse_result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(parse_result['rule'], parse_result['values'])
            flat['dna'] = dna_sequence
            flat['rule'] = parse_result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        except RuleParseError as e:
            outcome = TerminalOutcome.PARSE_ERROR
            error_msg = str(e)
            parsed_data = None

            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_sequence,
                'error': error_msg
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_sequence, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        latency_ms = (time.time() - start_time) * 1000

        results.append(DNAProcessingResult(
            dna_sequence=dna_sequence,
            terminal_outcome=outcome,
            parsed_data=parsed_data,
            error_message=error_msg,
            latency_ms=latency_ms
        ))

        # Update ledger WITHIN the loop
        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'latency_ms': latency_ms
        }
        log_structured(correlation_id, chain_name, "process_item", outcome.value,
                       latency_ms=latency_ms, idempotency_key=idempotency_key)
        new_processed_count += 1

    log_structured(correlation_id, chain_name, "batch_parsing", "SUCCESS", extra={"count": len(dna_sequences)})

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)

        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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
                # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

        # Save ledger
        save_ledger(ledger_path, ledger)

    log_structured(correlation_id, chain_name, "batch_complete", "SUCCESS",
                   extra={
                       "new_processed": new_processed_count,
                       "total_in_ledger": len(ledger),
                       "json_output": json_output_path,
                       "csv_output": csv_output_path
                   })

if __name__ == '__main__':
    main()
