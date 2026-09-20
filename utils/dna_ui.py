#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

# ─── EXPLICIT TERMINAL STATES & STATUS ENUM ───────────────────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# ─── EXCEPTION TAXONOMY ───────────────────────────────────────────────────────

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input file cannot be read."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger fails (e.g., corrupt JSON)."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic output file write or rename fails."""
    pass

# ─── STRUCTURED LOGGING UTILITY ──────────────────────────────────────────────

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key=None, outcome_detail=None):
    """
    Emits structured JSON telemetry logs prefixed with JSON_LOG:
    """
    log_data = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

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
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger file: {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

# ─── BATCH PARSER CHAIN ───────────────────────────────────────────────────────

def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())
    chain_name = "dna_batch_parser"

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step="start",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=(time.time() - start_time) * 1000
    )

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="input_check",
            outcome=DNAStatus.ERROR.value,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=f"Input file not found: {input_file}"
        )
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="load_rules",
            outcome=DNAStatus.ERROR.value,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=str(e)
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.SKIPPED.value,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail="No DNA sequences found in input file"
        )
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data.get('ledger', ledger_data) if isinstance(ledger_data, dict) and 'ledger' in ledger_data else ledger_data

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
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            existing_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step="deduplication",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=(time.time() - start_time) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit. Prior outcome: {existing_outcome}"
            )
            continue

        step_start = time.time()
        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_sequence
            flat['dna'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value

        except RuleParseError as e:
            parsed_json.append({
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,
                'error': str(e)
            })
            flat = {'dna_sequence': dna_sequence, 'dna': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="parse_sequence",
            outcome=outcome,
            latency_ms=(time.time() - step_start) * 1000,
            idempotency_key=idempotency_key
        )
        new_processed_count += 1

    if new_processed_count > 0:
        if isinstance(ledger_data, dict) and 'ledger' in ledger_data:
            ledger_data['ledger'] = ledger
            save_ledger(ledger_path, ledger_data)
        else:
            save_ledger(ledger_path, ledger)

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
                raise AtomicWriteError("Failed to write output files atomically") from e

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step="complete",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=(time.time() - start_time) * 1000,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

# Alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    main()
