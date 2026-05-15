#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Any, Dict
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

class TerminalOutcome(Enum):
    SUCCESS = "success"
    PARSE_ERROR = "parse_error"
    SKIPPED = "skipped"

@dataclass
class DNAProcessingResult:
    dna_sequence: str
    terminal_outcome: TerminalOutcome
    rule: Optional[str] = None
    parsed_data: Optional[Dict[str, Any]] = None
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

def log_structured(step, outcome, correlation_id=None, actor_id='system', chain_name='dna_batch_chain', latency_ms=None, **kwargs):
    """
    Standardized structured logging.
    """
    log_entry = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'chain_name': chain_name,
        'correlation_id': correlation_id or 'N/A',
        'actor_id': actor_id,
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms
    }
    log_entry.update(kwargs)
    print(json.dumps(log_entry))

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    correlation_id = str(uuid.uuid4())
    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(step='initialization', outcome='error', correlation_id=correlation_id, error=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(step='rule_loading', outcome='error', correlation_id=correlation_id, error=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequences = read_input_file(input_file)
    except Exception as e:
        log_structured(step='input_reading', outcome='error', correlation_id=correlation_id, error=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequences:
        log_structured(step='input_reading', outcome='skipped', correlation_id=correlation_id, reason="No DNA sequences found")
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
        start_time = time.time()
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(
                step='parsing',
                outcome='skipped',
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                reason='dedupe_hit',
                terminal_outcome=ledger[idempotency_key]['terminal_outcome']
            )
            continue

        try:
            parse_result = calculator.parse(dna_sequence)
            proc_result = DNAProcessingResult(
                dna_sequence=dna_sequence,
                terminal_outcome=TerminalOutcome.SUCCESS,
                rule=parse_result['rule'],
                parsed_data=parse_result['values']
            )

            entry = {
                'dna': proc_result.dna_sequence,
                'rule': proc_result.rule,
                'parsed': proc_result.parsed_data
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(proc_result.rule, proc_result.parsed_data)
            flat['dna'] = proc_result.dna_sequence
            flat['rule'] = proc_result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        except RuleParseError as e:
            proc_result = DNAProcessingResult(
                dna_sequence=dna_sequence,
                terminal_outcome=TerminalOutcome.PARSE_ERROR,
                error_message=str(e)
            )
            # On parse error, record as error entry
            parsed_json.append({
                'dna': proc_result.dna_sequence,
                'error': proc_result.error_message
            })
            # Also put a row in CSV listing error
            flat = {'dna': proc_result.dna_sequence, 'error': proc_result.error_message}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        # Update ledger and state
        latency_ms = int((time.time() - start_time) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': proc_result.terminal_outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_structured(
            step='parsing',
            outcome=proc_result.terminal_outcome.value,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            latency_ms=latency_ms
        )
        new_processed_count += 1

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

    log_structured(step='batch_complete', outcome='success', correlation_id=correlation_id, total_parsed=len(dna_sequences), new_processed=new_processed_count)

    if new_processed_count > 0:
        # Save ledger
        save_ledger(ledger_path, ledger)

        # Write JSON output
        with open(json_output_path, 'w', encoding='utf-8') as jf:
            json.dump(parsed_json, jf, indent=2)

        # Write CSV output
        fieldnames = sorted(all_flattened_keys)
        with open(csv_output_path, 'w', newline='', encoding='utf-8') as cf:
            writer = csv.DictWriter(cf, fieldnames=fieldnames)
            writer.writeheader()
            for row in csv_rows:
                # Ensure every field in fieldnames
                out = {k: row.get(k, '') for k in fieldnames}
                writer.writerow(out)


if __name__ == '__main__':
    main()
