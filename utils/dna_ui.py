#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from datetime import datetime, timezone
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# ─── EXCEPTION TAXONOMY ────────────────────────────────────────────────────────

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic write operations fail."""
    pass

# ─── TERMINAL STATES ───────────────────────────────────────────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# ─── STRUCTURED LOGGING ────────────────────────────────────────────────────────

def log_structured(
    correlation_id: str,
    actor_id: str,
    chain_name: str,
    step: str,
    outcome: str,
    latency_ms: float,
    idempotency_key: str = None,
    outcome_detail: str = None
):
    """Emits standardized JSON structured log entry."""
    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "system",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(payload)}")

# ─── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

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
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

# ─── CORE BATCH PROCESSING CHAIN ───────────────────────────────────────────────

def run_batch(correlation_id: str = None, actor_id: str = "batch_parser"):
    start_time = time.time()
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    chain_name = "dna_batch_parser"

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step="batch_started",
        outcome="in_progress",
        latency_ms=(time.time() - start_time) * 1000
    )

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="input_check",
            outcome=DNAStatus.REFUSED.value,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="input_check",
            outcome=DNAStatus.SKIPPED.value,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail="No DNA sequences found in input file"
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
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step="idempotency_check",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=(time.time() - start_time) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated (terminal outcome: {ledger[idempotency_key].get('terminal_outcome')})"
            )
            continue

        try:
            result = calculator.parse(dna_seq)
            entry = {
                'dna_sequence': dna_seq,
                'dna': dna_seq,  # Backwards compatibility key
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_seq
            flat['dna'] = dna_seq  # Backwards compatibility key
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value

        except RuleParseError as e:
            entry = {
                'dna_sequence': dna_seq,
                'dna': dna_seq,
                'error': str(e)
            }
            parsed_json.append(entry)
            flat = {'dna_sequence': dna_seq, 'dna': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="sequence_parsed",
            outcome=outcome,
            latency_ms=(time.time() - start_time) * 1000,
            idempotency_key=idempotency_key,
            outcome_detail=f"Parsed sequence with status {outcome}"
        )

    # ATOMIC WRITE PATTERN:
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
                raise AtomicWriteError("Failed to write output files atomically") from e

        # Save ledger
        save_ledger(ledger_path, ledger)

    total_latency = (time.time() - start_time) * 1000
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step="batch_completed",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=total_latency,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total ledger: {len(ledger)}"
    )

# Alias for backwards compatibility
main = run_batch

if __name__ == '__main__':
    main()
