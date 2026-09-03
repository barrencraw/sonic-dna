#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
from enum import Enum
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

# ─── EXPLICIT TERMINAL STATES & ERROR TAXONOMY ────────────────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base exception for all DNA processing failures."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input sequence file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when loading rules fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base exception for ledger or file output persistence failures."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when reading or parsing the ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file writes fail."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system exceeds thermal cooling thresholds."""
    pass


# ─── STRUCTURED LOGGING HYGIENE ────────────────────────────────────────────────

def log_structured(correlation_id, chain_name, step, outcome, latency_ms, actor_id, idempotency_key, outcome_detail=None):
    """
    Standardized structured logging emitter.
    """
    log_payload = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Enum) else str(outcome),
        "latency_ms": int(latency_ms),
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
    }
    if outcome_detail is not None:
        log_payload["outcome_detail"] = outcome_detail

    print(f"JSON_LOG: {json.dumps(log_payload)}")


# ─── UTILITY FUNCTIONS ────────────────────────────────────────────────────────

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
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Ledger file is corrupted: {ledger_path}") from e
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e


# ─── BATCH PROCESSING USE CASE ────────────────────────────────────────────────

def run_batch(correlation_id=None, actor_id="batch_parser"):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    start_time = time.time()
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            chain_name="dna_batch_parser",
            step="read_input",
            outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            idempotency_key="-",
            outcome_detail={"reason": "input_file_not_found", "path": input_file}
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequence list
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            chain_name="dna_batch_parser",
            step="read_input",
            outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            idempotency_key="-",
            outcome_detail={"reason": "empty_input_file"}
        )
        return

    ledger_data = load_ledger(ledger_path)
    # Support both structured ledger and legacy flat ledger layouts
    if isinstance(ledger_data, dict) and 'ledger' in ledger_data:
        ledger = ledger_data['ledger']
    else:
        ledger = ledger_data

    # Load existing JSON output
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

    # Load existing CSV rows
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
    for dna_sequence in dna_sequence_list:
        step_start = time.time()
        idempotency_key = dna_sequence

        if idempotency_key in ledger:
            existing_entry = ledger[idempotency_key]
            existing_outcome = existing_entry.get('terminal_outcome', DNAStatus.SUCCESS) if isinstance(existing_entry, dict) else DNAStatus.SUCCESS
            log_structured(
                correlation_id=correlation_id,
                chain_name="dna_batch_parser",
                step="idempotency_check",
                outcome=DNAStatus.SKIPPED,
                latency_ms=(time.time() - step_start) * 1000,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail={"dedupe_hit": True, "terminal_outcome": existing_outcome}
            )
            continue

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

        step_latency = (time.time() - step_start) * 1000
        log_structured(
            correlation_id=correlation_id,
            chain_name="dna_batch_parser",
            step="parse_sequence",
            outcome=outcome,
            latency_ms=step_latency,
            actor_id=actor_id,
            idempotency_key=idempotency_key
        )

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # Save ledger
        save_ledger(ledger_path, ledger_data)

        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in output folder
        # 2. Flush and sync files to disk
        # 3. Rename atomically using os.replace
        try:
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

                # Write JSON output
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # Write CSV output
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

    total_latency = (time.time() - start_time) * 1000
    log_structured(
        correlation_id=correlation_id,
        chain_name="dna_batch_parser",
        step="batch_complete",
        outcome=DNAStatus.SUCCESS,
        latency_ms=total_latency,
        actor_id=actor_id,
        idempotency_key="-",
        outcome_detail={"new_processed_count": new_processed_count, "total_ledger_count": len(ledger)}
    )

# Alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
