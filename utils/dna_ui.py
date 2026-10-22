#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# ─── EXPLICIT TERMINAL STATES & TYPED EXCEPTIONS ────────────────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base exception for DNA sequence processing pipeline."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input DNA sequence file cannot be read."""
    pass

class PersistenceError(DNAProcessingError):
    """Base exception for persistence failures."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass


# ─── STRUCTURED LOGGING HELPER ─────────────────────────────────────────────────

def log_structured(step, outcome, correlation_id=None, actor_id="batch_parser", latency_ms=0.0, idempotency_key=None, outcome_detail=None):
    """
    Standardized structured telemetry logger emitting JSON log events.
    """
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": "dna_batch_parser",
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")
    return log_entry


# ─── FILE UTILITIES & LEDGER MANAGEMENT ────────────────────────────────────────

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
    Useful for CSV export.
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


# ─── CORE BATCH PROCESSING ENTRYPOINT ──────────────────────────────────────────

def run_batch(correlation_id=None):
    start_time = time.time()
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured("read_input", DNAStatus.REFUSED.value, correlation_id=correlation_id, outcome_detail=f"Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured("load_rules", DNAStatus.ERROR.value, correlation_id=correlation_id, outcome_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured("read_input", DNAStatus.ERROR.value, correlation_id=correlation_id, outcome_detail=str(e))
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        log_structured("read_input", DNAStatus.SKIPPED.value, correlation_id=correlation_id, outcome_detail="No DNA sequences found in input file.")
        return

    ledger = load_ledger(ledger_path)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
        except Exception:
            parsed_json = []

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
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured("process_sequence", DNAStatus.SKIPPED.value, correlation_id=correlation_id, idempotency_key=idempotency_key, outcome_detail="Deduplication hit")
            continue

        seq_start = time.time()
        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,  # Retain legacy key for backwards compatibility
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_sequence
            flat['dna'] = dna_sequence  # Retain legacy key for backwards compatibility
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            terminal_outcome = DNAStatus.SUCCESS.value
            detail = f"Parsed using rule {result['rule']}"

        except RuleParseError as e:
            parsed_json.append({
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,  # Retain legacy key for backwards compatibility
                'error': str(e)
            })
            flat = {'dna_sequence': dna_sequence, 'dna': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            terminal_outcome = DNAStatus.ERROR.value
            detail = f"Parse error: {str(e)}"

        seq_latency = (time.time() - seq_start) * 1000.0
        ledger[idempotency_key] = {
            'terminal_outcome': terminal_outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_structured("process_sequence", terminal_outcome, correlation_id=correlation_id, latency_ms=seq_latency, idempotency_key=idempotency_key, outcome_detail=detail)
        new_processed_count += 1

    if new_processed_count > 0:
        try:
            save_ledger(ledger_path, ledger)
        except Exception as e:
            log_structured("save_ledger", DNAStatus.ERROR.value, correlation_id=correlation_id, outcome_detail=str(e))
            raise LedgerSaveError("Failed to save ledger") from e

        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

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

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                log_structured("atomic_write", DNAStatus.ERROR.value, correlation_id=correlation_id, outcome_detail=str(e))
                raise AtomicWriteError("Failed to write output files atomically") from e

    total_latency = (time.time() - start_time) * 1000.0
    log_structured("batch_complete", DNAStatus.SUCCESS.value, correlation_id=correlation_id, latency_ms=total_latency, outcome_detail=f"Processed {new_processed_count} new DNA sequence(s).")

# Alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
