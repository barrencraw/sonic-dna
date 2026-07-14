#!/usr/bin/env python3
import os
import json
import csv
import time
from enum import Enum
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
import datetime
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

@dataclass
class BatchResult:
    total_sequences: int
    newly_processed: int
    success_count: int
    error_count: int
    skipped_count: int

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

def log_structured(correlation_id: str, step: str, outcome: str,
                   latency_ms: Optional[float] = None,
                   idempotency_key: Optional[str] = None,
                   actor_id: str = "dna-processor-v1",
                   chain_name: str = "dna-batch-parse",
                   **kwargs):
    """
    Emits a structured JSON log to stdout with a unique prefix.
    """
    payload = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        **kwargs
    }
    print(f"JSON_LOG:{json.dumps(payload)}")

def run_batch(correlation_id: Optional[str] = None):
    if not correlation_id:
        import uuid
        correlation_id = str(uuid.uuid4())

    start_time = time.time()
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_sequences = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequences:
        print("[WARN] No DNA strings found in toSequence.txt")
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
    success_count = 0
    error_count = 0
    skipped_count = 0

    for dna_sequence in dna_sequences:
        idempotency_key = dna_sequence
        item_start = time.time()
        if idempotency_key in ledger:
            log_structured(
                correlation_id=correlation_id,
                step="deduplicate",
                outcome=DNAStatus.SKIPPED.value,
                idempotency_key=idempotency_key,
                outcome_detail=f"Already processed with outcome: {ledger[idempotency_key]['terminal_outcome']}"
            )
            skipped_count += 1
            continue

        log_structured(
            correlation_id=correlation_id,
            step="process_sequence",
            outcome="started",
            idempotency_key=idempotency_key
        )

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
            outcome = DNAStatus.SUCCESS.value
            outcome_detail = "Successfully parsed"
            success_count += 1

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
            outcome = DNAStatus.ERROR.value
            outcome_detail = str(e)
            error_count += 1

        ledger[idempotency_key] = {
            'terminal_outcome': f"{outcome}: {outcome_detail}" if outcome == DNAStatus.ERROR.value else outcome,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        }

        log_structured(
            correlation_id=correlation_id,
            step="process_sequence",
            outcome=outcome,
            latency_ms=round((time.time() - item_start) * 1000, 2),
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )
        new_processed_count += 1

    # ATOMIC COMMIT PATTERN:
    # All changes (Ledger, JSON, CSV) should be committed as a single logical unit.
    if new_processed_count > 0:
        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

        with tempfile.TemporaryDirectory(dir=os.path.dirname(ledger_path)) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                # 1) Write Ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 2) Write JSON output to temp
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 3) Write CSV output to temp
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 4) Atomic rename (commit)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                raise PersistenceError(f"Failed to commit changes atomically: {e}") from e

    # Output paths for visibility
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

    res = BatchResult(
        total_sequences=len(dna_sequences),
        newly_processed=new_processed_count,
        success_count=success_count,
        error_count=error_count,
        skipped_count=skipped_count
    )

    log_structured(
        correlation_id=correlation_id,
        step="batch_complete",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=round((time.time() - start_time) * 1000, 2),
        **asdict(res)
    )

    return res

if __name__ == '__main__':
    run_batch()
