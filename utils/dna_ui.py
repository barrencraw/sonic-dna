#!/usr/bin/env python3
import os
import sys
import json
import csv
import time
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Explicit Terminal States Enum ---
class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"

# --- Typed Error Hierarchy ---
class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input file cannot be read or accessed."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing, updating, or moving output/ledger files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when writing the ledger file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing or replacing output files atomically fails."""
    pass

# --- Observability / Structured Logging ---
def log_structured(step: str, outcome: str, latency_ms: float = 0.0,
                   idempotency_key: str = None, correlation_id: str = None,
                   actor_id: str = "batch_parser", chain_name: str = "dna_batch_parser",
                   error_type: str = None, message: str = ""):
    record = {
        "correlation_id": correlation_id or "trace-default",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "actor_id": actor_id,
        "idempotency_key": idempotency_key or "N/A"
    }
    if error_type:
        record["error_type"] = error_type
    if message:
        record["message"] = message

    # Emit JSON structured log line for observability / log scrapers
    print(f"JSON_LOG:{json.dumps(record)}")


def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequence_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequence_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_path}") from e
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None):
    start_total_time = time.perf_counter()
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            step="input_discovery",
            outcome=DNAStatus.SKIPPED.value,
            correlation_id=correlation_id,
            message=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            step="load_rules",
            outcome=DNAStatus.ERROR.value,
            correlation_id=correlation_id,
            error_type="RuleLoadError",
            message=str(e)
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        log_structured(
            step="input_discovery",
            outcome=DNAStatus.SKIPPED.value,
            correlation_id=correlation_id,
            message="No DNA sequences found in toSequence.txt"
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

    new_processed_count = 0
    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger:
            log_structured(
                step="idempotency_check",
                outcome=DNAStatus.SKIPPED.value,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                message=f"Dedupe hit; previous terminal_outcome={ledger[idempotency_key].get('terminal_outcome')}"
            )
            continue

        item_start_time = time.perf_counter()
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
            terminal_status = DNAStatus.SUCCESS

            item_latency_ms = (time.perf_counter() - item_start_time) * 1000.0
            log_structured(
                step="parse_sequence",
                outcome=terminal_status.value,
                latency_ms=item_latency_ms,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id
            )

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            terminal_status = DNAStatus.ERROR

            item_latency_ms = (time.perf_counter() - item_start_time) * 1000.0
            log_structured(
                step="parse_sequence",
                outcome=terminal_status.value,
                latency_ms=item_latency_ms,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                error_type="RuleParseError",
                message=str(e)
            )

        ledger[idempotency_key] = {
            'terminal_outcome': terminal_status.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)
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

            except Exception as e:
                log_structured(
                    step="atomic_write",
                    outcome=DNAStatus.ERROR.value,
                    correlation_id=correlation_id,
                    error_type="AtomicWriteError",
                    message="Failed to write output files atomically"
                )
                raise AtomicWriteError("Failed to write output files atomically") from e

        # Save ledger
        save_ledger(ledger_path, ledger)

    total_latency_ms = (time.perf_counter() - start_total_time) * 1000.0
    log_structured(
        step="batch_completed",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=total_latency_ms,
        correlation_id=correlation_id,
        message=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

# Alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
