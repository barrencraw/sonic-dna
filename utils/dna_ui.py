#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when the input file cannot be read."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading the ledger fails because it is corrupted or unreadable."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic write operations fail."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
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
        except Exception as e:
            raise LedgerLoadError(f"Ledger file exists but is corrupted or invalid: {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger):
    dir_name = os.path.dirname(ledger_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
            temp_name = tf.name
            json.dump(ledger, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(temp_name, ledger_path)
    except Exception as e:
        if temp_name and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically to {ledger_path}") from e

def log_structured(step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None, correlation_id=None):
    """
    Structured telemetry logging utility. Prints a JSON log prefixed with 'JSON_LOG:'.
    """
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "correlation_id": correlation_id or "N/A",
        "actor_id": "sonicdna_system",
        "chain_name": "dna_batch_parsing_chain",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or "N/A"
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

def run_batch(correlation_id=None):
    start_time = time.time()
    log_structured("batch_start", "success", correlation_id=correlation_id)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured("batch_end", "skipped", latency_ms=latency_ms, outcome_detail="Input file not found", correlation_id=correlation_id)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured("batch_end", "error", latency_ms=latency_ms, outcome_detail=f"RuleLoadError: {str(e)}", correlation_id=correlation_id)
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured("batch_end", "error", latency_ms=latency_ms, outcome_detail=f"InputReadError: {str(e)}", correlation_id=correlation_id)
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured("batch_end", "skipped", latency_ms=latency_ms, outcome_detail="No DNA sequences found in input file", correlation_id=correlation_id)
        return

    try:
        ledger = load_ledger(ledger_path)
    except LedgerLoadError as e:
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured("batch_end", "error", latency_ms=latency_ms, outcome_detail=f"LedgerLoadError: {str(e)}", correlation_id=correlation_id)
        raise

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
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            log_structured(
                "deduplicated", "skipped",
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated key; status={ledger[idempotency_key]['terminal_outcome']}",
                correlation_id=correlation_id
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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

            log_structured(
                "parsed", "success",
                idempotency_key=idempotency_key,
                outcome_detail="Successfully parsed DNA sequence",
                correlation_id=correlation_id
            )

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

            log_structured(
                "parsed", "error",
                idempotency_key=idempotency_key,
                outcome_detail=f"RuleParseError: {str(e)}",
                correlation_id=correlation_id
            )

        # Record outcome in ledger and increment new_processed_count
        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome.value}")
        new_processed_count += 1

    if new_processed_count > 0:
        # Save ledger atomically
        save_ledger(ledger_path, ledger)

        # Write output files atomically
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

    # Clear/drain the input file on successful completion of the batch run
    try:
        with open(input_file, 'w', encoding='utf-8') as f:
            pass
    except Exception as e:
        raise PersistenceError(f"Failed to clear input file: {input_file}") from e

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

    latency_ms = int((time.time() - start_time) * 1000)
    log_structured(
        "batch_end", "success",
        latency_ms=latency_ms,
        outcome_detail=f"Batch parsing completed. Processed {new_processed_count} new DNA sequences.",
        correlation_id=correlation_id
    )

# Alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    main()
