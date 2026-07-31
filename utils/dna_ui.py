#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
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

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
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
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    """
    Atomically saves the ledger file using a temporary file write, flush, fsync, and replace sequence,
    guarding against torn writes and ledger corruption.
    Gracefully handles exceptions by cleaning up partially written temporary files and raising a LedgerSaveError.
    """
    dir_name = os.path.dirname(ledger_path)
    if not dir_name:
        dir_name = '.'
    ensure_folder(dir_name)

    tf = None
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf_file:
            tf = tf_file
            temp_name = tf.name
            json.dump(ledger, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(temp_name, ledger_path)
    except Exception as e:
        if tf is not None:
            try:
                tf.close()
            except Exception:
                pass
        if temp_name and os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically: {e}") from e

def log_structured(step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None, correlation_id=None, actor_id="batch_parser", chain_name="dna_batch_parsing"):
    """
    Emits JSON logs with the JSON_LOG: prefix, including mandatory fields:
    timestamp (UTC ISO 8601), correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, and outcome_detail.
    """
    import datetime
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or "N/A"
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None):
    start_time = time.time()

    # Standardize step: batch_started
    log_structured(
        step="batch_started",
        outcome=DNAStatus.SUCCESS.value,
        correlation_id=correlation_id
    )

    # Output file paths defined once at the beginning of run_batch() to prevent UnboundLocalError
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
            step="input_check",
            outcome=DNAStatus.ERROR.value,
            outcome_detail=f"Input file not found: {input_file}",
            correlation_id=correlation_id
        )
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            step="calculator_init",
            outcome=DNAStatus.ERROR.value,
            outcome_detail=str(e),
            correlation_id=correlation_id
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings (canonical: dna_sequence_list)
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            step="input_read",
            outcome=DNAStatus.ERROR.value,
            outcome_detail=str(e),
            correlation_id=correlation_id
        )
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        log_structured(
            step="batch_empty",
            outcome=DNAStatus.SKIPPED.value,
            outcome_detail="No DNA strings found in toSequence.txt",
            correlation_id=correlation_id
        )
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)

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

    # Loop over dna_sequence_list using canonical name dna_sequence
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            terminal_outcome = ledger[idempotency_key]['terminal_outcome']
            # Standardized deduplication hit log
            log_structured(
                step="deduplication_check",
                outcome=DNAStatus.SKIPPED.value,
                idempotency_key=idempotency_key,
                outcome_detail=f"dedupe_hit=True terminal_outcome={terminal_outcome}",
                correlation_id=correlation_id
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
            continue

        log_structured(
            step="deduplication_check",
            outcome=DNAStatus.SUCCESS.value,
            idempotency_key=idempotency_key,
            outcome_detail="dedupe_hit=False terminal_outcome=processing",
            correlation_id=correlation_id
        )
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence, # Support both canonical and legacy
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence # Support both canonical and legacy
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            }
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        # Update ledger inside the loop as required by the contract and memory
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        log_structured(
            step="sequence_processed",
            outcome=outcome,
            idempotency_key=idempotency_key,
            outcome_detail=f"Processed sequence with outcome: {outcome}",
            correlation_id=correlation_id
        )
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # Save ledger and write files atomically ONLY if new_processed_count > 0
    if new_processed_count > 0:
        # 1) Save ledger atomically (can fail with LedgerSaveError)
        save_ledger(ledger_path, ledger)

        # 2) Atomic write sequence for JSON and CSV output files
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            try:
                # Write JSON output to temp
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # Write CSV output to temp
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                # Standardize logging
                log_structured(
                    step="atomic_write",
                    outcome=DNAStatus.ERROR.value,
                    outcome_detail=f"Atomic write failed: {str(e)}",
                    correlation_id=correlation_id
                )
                raise PersistenceError("Failed to write output files atomically") from e

    latency_ms = int((time.time() - start_time) * 1000)
    log_structured(
        step="batch_completed",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=latency_ms,
        outcome_detail=f"Processed {new_processed_count} new sequences. Total in ledger: {len(ledger)}",
        correlation_id=correlation_id
    )
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

# Maintain alias main for backward compatibility with imports in main.py and test suites
main = run_batch

if __name__ == '__main__':
    run_batch()
