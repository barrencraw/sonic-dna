#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input sequence file fails."""
    pass

class LedgerLoadError(DNAProcessingError):
    """Raised when loading or parsing ledger fails."""
    pass

class LedgerSaveError(DNAProcessingError):
    """Raised when saving ledger fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def log_structured(
    chain_name: str,
    step: str,
    outcome: str,
    latency_ms: float,
    correlation_id: str = None,
    actor_id: str = "batch_worker",
    idempotency_key: str = None,
    outcome_detail: str = None
):
    """
    Standardized structured logging emitter.
    """
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")
    return log_entry

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
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    chain_start = time.perf_counter()
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            chain_name="dna_batch_parser",
            step="input_check",
            outcome=DNAStatus.SKIPPED.value,
            latency_ms=(time.perf_counter() - chain_start) * 1000,
            correlation_id=correlation_id,
            outcome_detail=f"Input file not found: {input_file}"
        )
        print(f"[ERROR] Input file not found: {input_file}")
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
            chain_name="dna_batch_parser",
            step="input_read",
            outcome=DNAStatus.SKIPPED.value,
            latency_ms=(time.perf_counter() - chain_start) * 1000,
            correlation_id=correlation_id,
            outcome_detail="No DNA sequences found in input file"
        )
        print("[WARN] No DNA sequences found in toSequence.txt")
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
        seq_start = time.perf_counter()
        idempotency_key = dna_seq
        if idempotency_key in ledger:
            log_structured(
                chain_name="dna_batch_parser",
                step="deduplication",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=(time.perf_counter() - seq_start) * 1000,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated hit. Previous outcome: {ledger[idempotency_key]['terminal_outcome']}"
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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
            outcome_detail = f"Rule: {result['rule']}"

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna_sequence': dna_seq,
                'dna': dna_seq,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna_sequence': dna_seq, 'dna': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value
            outcome_detail = str(e)

        seq_latency = (time.perf_counter() - seq_start) * 1000
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_structured(
            chain_name="dna_batch_parser",
            step="sequence_parse",
            outcome=outcome,
            latency_ms=seq_latency,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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
                raise PersistenceError("Failed to write output files atomically") from e

        # Save ledger
        save_ledger(ledger_path, ledger)

    log_structured(
        chain_name="dna_batch_parser",
        step="batch_complete",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=(time.perf_counter() - chain_start) * 1000,
        correlation_id=correlation_id,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences out of {len(dna_sequence_list)} total."
    )
    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

# Maintain `main` alias for backward compatibility with imports/tests
main = run_batch

if __name__ == '__main__':
    main()
