#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Typed Terminal Status ---
class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# --- Typed Exception Taxonomy ---
class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when ledger or output persistence fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when reading/parsing ledger file fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass


# --- Structured Telemetry Logger ---
def log_structured(correlation_id, chain_name, step, outcome, latency_ms, actor_id, idempotency_key=None, outcome_detail=None):
    """
    Emits standardized structured telemetry log JSON prefixed with JSON_LOG:
    """
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    payload = {
        "timestamp": timestamp,
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(payload)}")


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
            raise LedgerLoadError(f"Failed to load ledger at {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
    """
    Executes a DNA sequence batch processing pipeline.
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
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="input_file_check",
            outcome=DNAStatus.ERROR.value,
            latency_ms=latency_ms,
            actor_id=actor_id,
            idempotency_key=None,
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
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="read_input_file",
            outcome=DNAStatus.SKIPPED.value,
            latency_ms=latency_ms,
            actor_id=actor_id,
            idempotency_key=None,
            outcome_detail="No DNA sequences found in toSequence.txt"
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
        seq_start_time = time.time()
        idempotency_key = dna_sequence

        if idempotency_key in ledger:
            seq_latency = int((time.time() - seq_start_time) * 1000)
            terminal_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            log_structured(
                correlation_id=correlation_id,
                chain_name=chain_name,
                step="deduplication_check",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=seq_latency,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit, prior outcome: {terminal_outcome}"
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
            outcome = DNAStatus.SUCCESS.value
            outcome_detail = f"Successfully parsed rule {result['rule']}"

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
            outcome = DNAStatus.ERROR.value
            outcome_detail = str(e)

        seq_latency = int((time.time() - seq_start_time) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="parse_sequence",
            outcome=outcome,
            latency_ms=seq_latency,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
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

        # Save ledger after successful atomic write
        save_ledger(ledger_path, ledger)

    batch_latency = int((time.time() - start_time) * 1000)
    log_structured(
        correlation_id=correlation_id,
        chain_name=chain_name,
        step="batch_complete",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=batch_latency,
        actor_id=actor_id,
        idempotency_key=None,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

# Alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    main()
