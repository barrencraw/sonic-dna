#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from enum import Enum
from dataclasses import dataclass, asdict
from utils.dna_calculator import DNACalculator, RuleParseError

class TerminalOutcome(Enum):
    SUCCESS = "success"
    PARSE_ERROR = "parse_error"
    SKIPPED = "skipped"

@dataclass
class DNAProcessingResult:
    dna_sequence: str
    terminal_outcome: TerminalOutcome
    error_message: str = None
    latency_ms: float = 0

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def log_structured(step, correlation_id, outcome="success", dna_sequence=None, latency_ms=0, error=None):
    """ Standardized structured logging. """
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id,
        "actor_id": "system",
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
    }
    if dna_sequence:
        log_entry["idempotency_key"] = dna_sequence
    if error:
        log_entry["error"] = str(error)

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

def main():
    start_time = time.time()
    correlation_id = str(uuid.uuid4())

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    if not os.path.isfile(input_file):
        log_structured("initialize", correlation_id, outcome="error", error=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured("load_rules", correlation_id, outcome="error", error=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequences = read_input_file(input_file)
    except Exception as e:
        log_structured("read_input", correlation_id, outcome="error", error=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequences:
        log_structured("process_batch", correlation_id, outcome="skipped", error="No DNA sequences found in toSequence.txt")
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
        seq_start = time.time()
        if dna_sequence in ledger:
            log_structured("process_sequence", correlation_id, outcome=TerminalOutcome.SKIPPED.value, dna_sequence=dna_sequence)
            continue

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = TerminalOutcome.SUCCESS
            error_msg = None

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_sequence,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = TerminalOutcome.PARSE_ERROR
            error_msg = str(e)

        seq_latency = (time.time() - seq_start) * 1000

        # Using the dataclass just to capture the result metadata
        res_obj = DNAProcessingResult(
            dna_sequence=dna_sequence,
            terminal_outcome=outcome,
            error_message=error_msg,
            latency_ms=seq_latency
        )

        log_structured(
            "process_sequence",
            correlation_id,
            outcome=res_obj.terminal_outcome.value,
            dna_sequence=res_obj.dna_sequence,
            latency_ms=res_obj.latency_ms,
            error=res_obj.error_message
        )

        ledger[dna_sequence] = {
            'terminal_outcome': res_obj.terminal_outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                # 1) Write JSON
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) Write CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Write Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # Atomic renames
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                log_structured("atomic_commit", correlation_id, outcome="error", error=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

    batch_latency = (time.time() - start_time) * 1000
    log_structured("batch_complete", correlation_id, outcome="success", latency_ms=batch_latency)

if __name__ == '__main__':
    main()
