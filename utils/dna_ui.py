#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
from enum import Enum
from datetime import datetime, timezone

from utils.dna_calculator import DNACalculator, RuleParseError

# ─── CANONICAL TERMINAL STATES & ERROR TAXONOMY ────────────────────────────────

class DNAStatus(str, Enum):
    """
    Explicit canonical terminal states for DNA processing steps and ledger records.
    Lowercase values ensure backward compatibility with existing tests.
    """
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for all DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded or initialized."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when the input raw file cannot be read."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for file persistence and atomic commit failures."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading the processed ledger fails or data is corrupted."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing or renaming output files atomically fails."""
    pass

# ─── OBSERVABILITY HYGIENE ────────────────────────────────────────────────────

def log_structured(
    correlation_id: str,
    chain_name: str,
    step: str,
    outcome: str,
    latency_ms: float = 0.0,
    actor_id: str = "batch_parser",
    idempotency_key: str = None,
    outcome_detail: str = None
):
    """
    Standardized structured logging for observability hygiene.
    Emits a structured JSON log line prefixed with JSON_LOG:.
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
    }
    if outcome_detail:
        record["outcome_detail"] = outcome_detail
    print(f"JSON_LOG:{json.dumps(record)}")
    return record

# ─── UTILITIES ────────────────────────────────────────────────────────────────

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequences = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequences.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file {input_path}") from e
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    raise LedgerLoadError(f"Ledger file at {ledger_path} is not a valid JSON object")
                return data
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Corrupted JSON in ledger file: {ledger_path}") from e
        except PersistenceError:
            raise
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

# ─── CORE BATCH PROCESSING CHAIN ──────────────────────────────────────────────

def run_batch(correlation_id=None, actor_id="batch_parser"):
    batch_start = time.perf_counter()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    chain_name = "dna_batch_parser"

    log_structured(
        correlation_id=correlation_id,
        chain_name=chain_name,
        step="batch_start",
        outcome=DNAStatus.SUCCESS.value,
        actor_id=actor_id
    )

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
            step="input_file_check",
            outcome=DNAStatus.SKIPPED.value,
            actor_id=actor_id,
            outcome_detail=f"Input file not found: {input_file}"
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
            outcome=DNAStatus.ERROR.value,
            actor_id=actor_id,
            outcome_detail=str(e)
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.ERROR.value,
            actor_id=actor_id,
            outcome_detail=str(e)
        )
        raise

    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.SKIPPED.value,
            actor_id=actor_id,
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
    for dna_sequence in dna_sequence_list:
        seq_start = time.perf_counter()
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(
                correlation_id=correlation_id,
                chain_name=chain_name,
                step="idempotency_check",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=(time.perf_counter() - seq_start) * 1000.0,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"dedupe_hit=True terminal_outcome={ledger[idempotency_key].get('terminal_outcome')}"
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
            detail = f"rule={result['rule']}"

        except RuleParseError as e:
            # On parse error, record as error entry
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            }
            parsed_json.append(entry)

            # Also put a row in CSV listing error
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            terminal_status = DNAStatus.ERROR
            detail = str(e)

        seq_latency = (time.perf_counter() - seq_start) * 1000.0
        ledger[idempotency_key] = {
            'terminal_outcome': terminal_status.value,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="sequence_parsed",
            outcome=terminal_status.value,
            latency_ms=seq_latency,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            outcome_detail=detail
        )
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are physically on disk
    # 3. Rename them to their final destination
    if new_processed_count > 0:
        commit_start = time.perf_counter()
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
                    correlation_id=correlation_id,
                    chain_name=chain_name,
                    step="atomic_write",
                    outcome=DNAStatus.ERROR.value,
                    latency_ms=(time.perf_counter() - commit_start) * 1000.0,
                    actor_id=actor_id,
                    outcome_detail=str(e)
                )
                raise AtomicWriteError("Failed to write output files atomically") from e

        save_ledger(ledger_path, ledger)

    batch_latency = (time.perf_counter() - batch_start) * 1000.0
    log_structured(
        correlation_id=correlation_id,
        chain_name=chain_name,
        step="batch_complete",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=batch_latency,
        actor_id=actor_id,
        outcome_detail=f"processed_count={new_processed_count} total_ledger={len(ledger)}"
    )

# Backward-compatible alias
main = run_batch

if __name__ == '__main__':
    run_batch()
