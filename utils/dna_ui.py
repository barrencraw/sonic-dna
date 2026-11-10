#!/usr/bin/env python3
import os
import json
import csv
import time
from utils.dna_calculator import DNACalculator, RuleParseError

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequence_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_sequence_list.append(s)
    return dna_sequence_list

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
import uuid
from datetime import datetime, timezone

from enum import Enum

class DNAStatus(str, Enum):
    """Explicit terminal outcomes for DNA sequence processing."""
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input sequence file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing, moving, or persisting files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when reading or deserializing processed ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when writing or serializing processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file writes fail."""
    pass

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}

def log_structured(
    correlation_id: str,
    chain_name: str,
    step: str,
    outcome: str,
    latency_ms: float,
    actor_id: str,
    idempotency_key: str = None,
    **extra
):
    """
    Standardized structured logging for observability.
    Emits a single-line JSON log with prefix 'JSON_LOG:' containing mandatory fields.
    """
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
    }
    if extra:
        payload["extra"] = extra
    print(f"JSON_LOG:{json.dumps(payload)}")

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
    """
    Core entry point for batch DNA sequence parsing.
    Accepts correlation_id and actor_id for observability tracing.
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    chain_name = "dna_batch_parser"
    start_time = time.time()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="check_input_file",
            outcome="missing_input_file",
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            file_path=input_file
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="load_rules",
            outcome="rule_load_error",
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            error=str(e)
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    step_start = time.time()
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="read_input_file",
            outcome="input_read_error",
            latency_ms=(time.time() - step_start) * 1000,
            actor_id=actor_id,
            error=str(e)
        )
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="read_input_file",
            outcome="empty_sequence_list",
            latency_ms=(time.time() - step_start) * 1000,
            actor_id=actor_id
        )
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
    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        item_start = time.time()
        if idempotency_key in ledger:
            # Dedupe hit decision point
            log_structured(
                correlation_id=correlation_id,
                chain_name=chain_name,
                step="dedupe_check",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=(time.time() - item_start) * 1000,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                dedupe_hit=True,
                recorded_outcome=ledger[idempotency_key]['terminal_outcome']
            )
            continue

        try:
            result = calculator.parse(dna_seq)
            entry = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_seq
            flat['dna_sequence'] = dna_seq
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            status = DNAStatus.SUCCESS
            detail = None

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            status = DNAStatus.ERROR
            detail = str(e)

        item_latency = (time.time() - item_start) * 1000
        ledger_entry = {
            'terminal_outcome': status.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        if detail:
            ledger_entry['error_detail'] = detail
        ledger[idempotency_key] = ledger_entry

        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="parse_sequence",
            outcome=status.value,
            latency_ms=item_latency,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            dedupe_hit=False
        )
        new_processed_count += 1

    if new_processed_count > 0:
        commit_start = time.time()
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
                log_structured(
                    correlation_id=correlation_id,
                    chain_name=chain_name,
                    step="atomic_write",
                    outcome="persistence_error",
                    latency_ms=(time.time() - commit_start) * 1000,
                    actor_id=actor_id,
                    error=str(e)
                )
                raise AtomicWriteError("Failed to write output files atomically") from e

        # Save ledger
        save_ledger(ledger_path, ledger)

    total_latency = (time.time() - start_time) * 1000
    log_structured(
        correlation_id=correlation_id,
        chain_name=chain_name,
        step="complete_batch",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=total_latency,
        actor_id=actor_id,
        new_processed_count=new_processed_count,
        total_in_ledger=len(ledger)
    )

main = run_batch

if __name__ == '__main__':
    main()
