#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
from utils.dna_calculator import DNACalculator, RuleParseError

def log_structured(correlation_id, step, outcome, latency_ms=0.0, idempotency_key=None, outcome_detail=None, actor_id="batch_parser"):
    # Output timestamp as ISO 8601 in UTC, ending in Z
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    timestamp_str = now_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    log_entry = {
        "timestamp": timestamp_str,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": "dna_batch_parser",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or ""
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

import tempfile
import shutil

class DNAProcessingError(Exception):
    """Base class for all DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input file cannot be read."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence-related errors."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when the ledger cannot be saved."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when the atomic file replacement fails."""
    pass

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    ledger_dir = os.path.dirname(ledger_path)
    ensure_folder(ledger_dir)
    tmp_path = None
    try:
        # Create a temporary file in the same directory as ledger
        fd, tmp_path = tempfile.mkstemp(dir=ledger_dir, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # Atomic replacement of the ledger file
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        # Clean up partial temporary file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically to {ledger_path}") from e

def run_batch(correlation_id=None):
    if correlation_id is None:
        import uuid
        correlation_id = str(uuid.uuid4())

    start_batch = time.perf_counter()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
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

    from utils.dna_calculator import RuleParseError

    new_processed_count = 0
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(
                correlation_id=correlation_id,
                step="deduplication",
                outcome="skipped",
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplication hit. Sequence terminal outcome: {ledger[idempotency_key]['terminal_outcome']}"
            )
            continue

        start_parse = time.perf_counter()
        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

            latency_ms = round((time.perf_counter() - start_parse) * 1000.0, 2)
            log_structured(
                correlation_id=correlation_id,
                step="parsing",
                outcome="success",
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=f"Successfully parsed sequence under rule {result['rule']}"
            )

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error"

            latency_ms = round((time.perf_counter() - start_parse) * 1000.0, 2)
            log_structured(
                correlation_id=correlation_id,
                step="parsing",
                outcome="error",
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=str(e)
            )

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    if new_processed_count > 0:
        start_persist = time.perf_counter()
        try:
            # Save ledger
            save_ledger(ledger_path, ledger)

            # ATOMIC WRITE PATTERN:
            # 1. Write to a temporary directory in the same filesystem as the output folder
            # 2. Flush and sync files to ensure they are on disk
            # 3. Rename them to their final destination (atomic on most OSes)
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
                    # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

                except Exception as e:
                    raise AtomicWriteError("Failed to write output files atomically") from e

            latency_ms = round((time.perf_counter() - start_persist) * 1000.0, 2)
            log_structured(
                correlation_id=correlation_id,
                step="persistence",
                outcome="success",
                latency_ms=latency_ms,
                outcome_detail=f"Committed {new_processed_count} new processed sequences to ledger and output files"
            )

        except Exception as e:
            latency_ms = round((time.perf_counter() - start_persist) * 1000.0, 2)
            log_structured(
                correlation_id=correlation_id,
                step="persistence",
                outcome="error",
                latency_ms=latency_ms,
                outcome_detail=str(e)
            )
            raise

    total_latency_ms = round((time.perf_counter() - start_batch) * 1000.0, 2)
    log_structured(
        correlation_id=correlation_id,
        step="complete",
        outcome="success",
        latency_ms=total_latency_ms,
        outcome_detail=f"Batch parsing execution complete. Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

main = run_batch

if __name__ == '__main__':
    main()
