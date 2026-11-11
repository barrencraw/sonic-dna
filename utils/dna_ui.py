#!/usr/bin/env python3
"""
utils/dna_ui.py

Batch parser for SonicDNA sequences.
Provides typed error classifications, explicit terminal states, structured logging,
and atomic file operations.
"""

import os
import sys
import json
import csv
import time
import uuid
import tempfile
from enum import Enum
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError, DNAProcessingError

# ─── TYPED ERROR TAXONOMY ──────────────────────────────────────────────────────

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence-related errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing the ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic output file writing fails."""
    pass

# ─── EXPLICIT TERMINAL STATES ──────────────────────────────────────────────────

class DNAStatus(str, Enum):
    """Terminal outcomes for DNA processing."""
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# ─── OBSERVABILITY & STRUCTURED LOGGING ────────────────────────────────────────

def log_structured(correlation_id: str, actor_id: str, chain_name: str,
                   step: str, outcome: str, latency_ms: float = 0.0,
                   idempotency_key: str = "", outcome_detail: str = ""):
    """
    Standardized structured logging for observability.
    Emits single-line JSON log prefixed with 'JSON_LOG:' for filtering.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 3),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(entry)}")

# ─── HELPERS ───────────────────────────────────────────────────────────────────

def ensure_folder(path: str):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path: str):
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

def flatten_parsed(rule_name: str, values_dict: dict, parent_key: str = ''):
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

def load_ledger(ledger_path: str):
    """
    Loads ledger file. Raises LedgerLoadError if corrupted.
    Returns empty dict if file does not exist.
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}: {e}") from e
    return {}

def save_ledger(ledger_path: str, ledger: dict):
    """
    Saves ledger to file. Raises LedgerSaveError on failure.
    """
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e

# ─── BATCH PROCESSING CHAIN ────────────────────────────────────────────────────

def run_batch(correlation_id: str = None, actor_id: str = "batch_parser"):
    """
    Process DNA sequence queue idempotently and atomically.
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    chain_name = "dna_batch_parser"
    start_time = time.perf_counter()

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step="start",
        outcome=DNAStatus.SUCCESS.value,
        outcome_detail="Batch parsing sequence initiated"
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
            step="check_input",
            outcome=DNAStatus.SKIPPED.value,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.SKIPPED.value,
            outcome_detail="No DNA sequences found in input"
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

    for dna_sequence in dna_sequence_list:
        seq_start = time.perf_counter()
        idempotency_key = dna_sequence

        if idempotency_key in ledger:
            existing_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS.value)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step="deduplicate",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=(time.perf_counter() - seq_start) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit with previous outcome: {existing_outcome}"
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
            terminal_status = DNAStatus.SUCCESS
            detail = f"Rule parsed: {result['rule']}"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            terminal_status = DNAStatus.ERROR
            detail = str(e)

        ledger[idempotency_key] = {
            'terminal_outcome': terminal_status.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="parse_sequence",
            outcome=terminal_status.value,
            latency_ms=(time.perf_counter() - seq_start) * 1000,
            idempotency_key=idempotency_key,
            outcome_detail=detail
        )

    # ATOMIC WRITE PATTERN
    # Only rewrite outputs and update ledger if new items were processed
    if new_processed_count > 0:
        commit_start = time.perf_counter()
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            try:
                # 1) Write JSON to temp
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) Write CSV to temp
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Atomic rename
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                raise AtomicWriteError(f"Failed to write output files atomically: {e}") from e

        # Save ledger
        save_ledger(ledger_path, ledger)

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="commit_outputs",
            outcome=DNAStatus.SUCCESS.value,
            latency_ms=(time.perf_counter() - commit_start) * 1000,
            outcome_detail=f"Committed {new_processed_count} new records"
        )

    total_latency_ms = (time.perf_counter() - start_time) * 1000
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step="end",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=total_latency_ms,
        outcome_detail=f"Processed {new_processed_count} new sequences, total ledger: {len(ledger)}"
    )

# Alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    main()
