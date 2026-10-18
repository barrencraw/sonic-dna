#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus:
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input files fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence and writing errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing the ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing or moving output files fails."""
    pass

def log_structured(
    correlation_id: str,
    chain_name: str,
    step: str,
    outcome: str,
    latency_ms: float,
    actor_id: str = "batch_parser",
    idempotency_key: str = None,
    outcome_detail: str = ""
):
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 3),
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequence_list = []
    if not os.path.exists(input_path):
        return dna_sequence_list
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequence_list.append(s)
        return dna_sequence_list
    except Exception as e:
        raise InputReadError(f"Failed to read input file {input_path}: {e}") from e

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
                return data if isinstance(data, dict) else {}
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger at {ledger_path}: {e}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger at {ledger_path}: {e}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
    batch_start_time = time.time()
    chain_name = "dna_batch_parser"
    correlation_id = correlation_id or str(uuid.uuid4())

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
            outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - batch_start_time) * 1000,
            actor_id=actor_id,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    rules_folder = os.path.join(project_root, 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {rules_folder}: {e}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - batch_start_time) * 1000,
            actor_id=actor_id,
            outcome_detail="No DNA sequences found in input file"
        )
        return

    ledger = load_ledger(ledger_path)

    # Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                content = json.load(jf)
                if isinstance(content, list):
                    parsed_json = content
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
    for dna_seq in dna_sequence_list:
        seq_start_time = time.time()
        idempotency_key = dna_seq

        if idempotency_key in ledger:
            log_structured(
                correlation_id=correlation_id,
                chain_name=chain_name,
                step="parse_sequence",
                outcome=DNAStatus.SKIPPED,
                latency_ms=(time.time() - seq_start_time) * 1000,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit. Terminal outcome: {ledger[idempotency_key].get('terminal_outcome')}"
            )
            continue

        try:
            result = calculator.parse(dna_seq)
            entry = {
                'dna_sequence': dna_seq,
                'dna': dna_seq,  # backward compatibility
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_seq
            flat['dna'] = dna_seq  # backward compatibility
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.SUCCESS
            outcome_detail = f"Successfully parsed using rule '{result['rule']}'"

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

            outcome = DNAStatus.ERROR
            outcome_detail = str(e)

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
            latency_ms=(time.time() - seq_start_time) * 1000,
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

        save_ledger(ledger_path, ledger)

    log_structured(
        correlation_id=correlation_id,
        chain_name=chain_name,
        step="batch_complete",
        outcome=DNAStatus.SUCCESS,
        latency_ms=(time.time() - batch_start_time) * 1000,
        actor_id=actor_id,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

main = run_batch

if __name__ == '__main__':
    run_batch()
