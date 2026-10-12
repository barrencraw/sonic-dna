#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
from datetime import datetime, timezone
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError


class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"


class DNAProcessingError(Exception):
    """Base exception for all DNA processing failures."""
    pass


class InputReadError(DNAProcessingError):
    """Raised when reading the input DNA sequence file fails."""
    pass


class RuleLoadError(DNAProcessingError):
    """Raised when loading calculator rules fails."""
    pass


class PersistenceError(DNAProcessingError):
    """Base class for persistence and file state errors."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing the processed ledger fails."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass


def log_structured(correlation_id, chain_name, step, outcome, latency_ms, actor_id, idempotency_key, outcome_detail=None):
    """
    Emits a standardized structured JSON log entry for observability hygiene.
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")


def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def read_input_file(input_path):
    """
    Reads `toSequence.txt`; each line is one DNA sequence.
    Returns a list of stripped, non-empty DNA sequences.
    """
    dna_sequence_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequence_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file '{input_path}': {e}") from e
    return dna_sequence_list


def flatten_parsed(rule_name, values_dict, parent_key=''):
    """
    Flatten nested dictionary into dot-separated keys for CSV output.
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
            raise LedgerLoadError(f"Corrupted or invalid ledger JSON at '{ledger_path}': {e}") from e
    return {}


def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save processed ledger to '{ledger_path}': {e}") from e


def run_batch(correlation_id=None):
    start_time = time.time()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    chain_name = "dna_batch_parser"
    actor_id = "batch_parser"

    log_structured(
        correlation_id=correlation_id,
        chain_name=chain_name,
        step="start",
        outcome=DNAStatus.SUCCESS,
        latency_ms=(time.time() - start_time) * 1000,
        actor_id=actor_id,
        idempotency_key="batch"
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
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.ERROR,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            idempotency_key="batch",
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            idempotency_key="batch",
            outcome_detail="No DNA sequences found in input file"
        )
        return

    ledger = load_ledger(ledger_path)

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
        seq_start = time.time()
        idempotency_key = dna_sequence

        if idempotency_key in ledger:
            existing_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS)
            log_structured(
                correlation_id=correlation_id,
                chain_name=chain_name,
                step="dedupe_check",
                outcome=DNAStatus.SKIPPED,
                latency_ms=(time.time() - seq_start) * 1000,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit with prior outcome: {existing_outcome}"
            )
            continue

        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="dedupe_check",
            outcome="miss",
            latency_ms=(time.time() - seq_start) * 1000,
            actor_id=actor_id,
            idempotency_key=idempotency_key
        )

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
            terminal_outcome = DNAStatus.SUCCESS
            error_msg = None

        except RuleParseError as e:
            error_msg = str(e)
            parsed_json.append({
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,
                'error': error_msg
            })
            flat = {'dna_sequence': dna_sequence, 'dna': dna_sequence, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            terminal_outcome = DNAStatus.ERROR

        ledger[idempotency_key] = {
            'terminal_outcome': terminal_outcome,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="parse_sequence",
            outcome=terminal_outcome,
            latency_ms=(time.time() - seq_start) * 1000,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            outcome_detail=error_msg
        )

    write_start = time.time()
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
        chain_name=chain_name,
        step="atomic_write",
        outcome=DNAStatus.SUCCESS,
        latency_ms=(time.time() - write_start) * 1000,
        actor_id=actor_id,
        idempotency_key="batch"
    )

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger)

    log_structured(
        correlation_id=correlation_id,
        chain_name=chain_name,
        step="complete",
        outcome=DNAStatus.SUCCESS,
        latency_ms=(time.time() - start_time) * 1000,
        actor_id=actor_id,
        idempotency_key="batch",
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total ledger size: {len(ledger)}"
    )


main = run_batch


if __name__ == '__main__':
    main()
