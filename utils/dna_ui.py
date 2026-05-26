#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from dataclasses import dataclass
from utils.dna_calculator import DNACalculator, RuleParseError

class TerminalOutcome(Enum):
    SUCCESS = "SUCCESS"
    PARSE_ERROR = "PARSE_ERROR"
    SKIPPED = "SKIPPED"

@dataclass
class DNAProcessingResult:
    dna_sequence: str
    terminal_outcome: TerminalOutcome
    error_message: str = None
    parsed_data: dict = None

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def log_structured(correlation_id, step, outcome_val, idempotency_key=None, latency_ms=None, **kwargs):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": str(correlation_id),
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome_val,
        "actor_id": "batch_processor"
    }
    if idempotency_key:
        log_entry["idempotency_key"] = idempotency_key
    if latency_ms is not None:
        log_entry["latency_ms"] = latency_ms
    log_entry.update(kwargs)
    print(json.dumps(log_entry))

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

def main(correlation_id=None):
    if correlation_id is None:
        correlation_id = uuid.uuid4()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    log_structured(correlation_id, "batch_init", "START")

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, "input_check", "ERROR", error_message=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, "calculator_init", "ERROR")
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, "read_input", "ERROR")
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured(correlation_id, "batch_process", "SKIPPED", error_message="No DNA strings found")
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
    batch_start_time = time.time()
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            log_structured(correlation_id, "deduplication", TerminalOutcome.SKIPPED.value, idempotency_key=idempotency_key)
            continue

        start_time = time.time()
        try:
            result = calculator.parse(dna_str)
            processed_result = DNAProcessingResult(
                dna_sequence=dna_str,
                terminal_outcome=TerminalOutcome.SUCCESS,
                parsed_data=result['values']
            )

            entry = {
                'dna_sequence': processed_result.dna_sequence,
                'rule': result['rule'],
                'parsed': processed_result.parsed_data
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], processed_result.parsed_data)
            flat['dna_sequence'] = processed_result.dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome_str = processed_result.terminal_outcome.value

        except RuleParseError as e:
            processed_result = DNAProcessingResult(
                dna_sequence=dna_str,
                terminal_outcome=TerminalOutcome.PARSE_ERROR,
                error_message=str(e)
            )
            # On parse error, record as error entry
            parsed_json.append({
                'dna_sequence': processed_result.dna_sequence,
                'error': processed_result.error_message
            })
            # Also put a row in CSV listing error
            flat = {'dna_sequence': processed_result.dna_sequence, 'error': processed_result.error_message}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome_str = processed_result.terminal_outcome.value

        latency = int((time.time() - start_time) * 1000)
        log_structured(correlation_id, "sequence_parse", outcome_str, idempotency_key=idempotency_key, latency_ms=latency)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome_str,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
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

                # Save ledger last as it marks completion
                save_ledger(ledger_path, ledger)

            except Exception as e:
                log_structured(correlation_id, "atomic_write", "ERROR", error_message=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    batch_latency = int((time.time() - batch_start_time) * 1000)
    log_structured(correlation_id, "batch_complete", "SUCCESS", latency_ms=batch_latency)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
