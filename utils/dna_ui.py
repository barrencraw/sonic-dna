#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class BatchResult:
    def __init__(self, status: DNAStatus, processed_count: int, error: Exception = None):
        self.status = status
        self.processed_count = processed_count
        self.error = error

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

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
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
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def log_structured(correlation_id, step, outcome, latency_ms=None, actor_id="orchestrator", idempotency_key=None, outcome_detail=None):
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": "dna_batch_parsing",
        "step": step,
        "outcome": outcome.value if isinstance(outcome, DNAStatus) else outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None, actor_id="orchestrator"):
    start_time = time.time()

    # Standardize structured log: batch start
    log_structured(
        correlation_id=correlation_id,
        step="start",
        outcome=DNAStatus.SUCCESS,
        actor_id=actor_id,
        outcome_detail="Starting DNA batch parsing."
    )

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured(
            correlation_id=correlation_id,
            step="end",
            outcome=DNAStatus.SKIPPED,
            latency_ms=latency_ms,
            actor_id=actor_id,
            outcome_detail=f"Input file not found: {input_file}"
        )
        print(f"[ERROR] Input file not found: {input_file}")
        return BatchResult(DNAStatus.SKIPPED, 0, FileNotFoundError(f"Input file not found: {input_file}"))

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured(
            correlation_id=correlation_id,
            step="end",
            outcome=DNAStatus.ERROR,
            latency_ms=latency_ms,
            actor_id=actor_id,
            outcome_detail=f"Could not load rules from {os.path.join(project_root, 'rules')}: {str(e)}"
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured(
            correlation_id=correlation_id,
            step="end",
            outcome=DNAStatus.ERROR,
            latency_ms=latency_ms,
            actor_id=actor_id,
            outcome_detail=f"Failed to read input file {input_file}: {str(e)}"
        )
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured(
            correlation_id=correlation_id,
            step="end",
            outcome=DNAStatus.SKIPPED,
            latency_ms=latency_ms,
            actor_id=actor_id,
            outcome_detail="No DNA strings found in toSequence.txt"
        )
        print("[WARN] No DNA strings found in toSequence.txt")
        return BatchResult(DNAStatus.SKIPPED, 0)

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
    error_occurred = False
    processing_exception = None

    try:
        for dna_sequence in dna_sequence_list:
            idempotency_key = dna_sequence
            if idempotency_key in ledger:
                terminal_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS)
                log_structured(
                    correlation_id=correlation_id,
                    step="deduplicate",
                    outcome=DNAStatus.SKIPPED,
                    actor_id=actor_id,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Deduplication hit. Already processed with status: {terminal_outcome}"
                )
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
            single_start = time.time()
            log_structured(
                correlation_id=correlation_id,
                step="process_single",
                outcome=DNAStatus.SUCCESS,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail="Processing DNA sequence."
            )

            try:
                result = calculator.parse(dna_sequence)
                entry = {
                    'dna': dna_sequence,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_sequence
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.SUCCESS
                outcome_detail = "Successfully parsed DNA sequence."

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_sequence,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna': dna_sequence, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR
                outcome_detail = f"Parse error: {str(e)}"

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            new_processed_count += 1
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")

            single_latency_ms = int((time.time() - single_start) * 1000)
            log_structured(
                correlation_id=correlation_id,
                step="process_single_done",
                outcome=outcome,
                latency_ms=single_latency_ms,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail
            )

    except Exception as e:
        error_occurred = True
        processing_exception = e

    # ATOMIC WRITE PATTERN: Only write if new items were processed and no fatal loop exception occurred
    if new_processed_count > 0 and not error_occurred:
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
                latency_ms = int((time.time() - start_time) * 1000)
                log_structured(
                    correlation_id=correlation_id,
                    step="commit_files",
                    outcome=DNAStatus.ERROR,
                    latency_ms=latency_ms,
                    actor_id=actor_id,
                    outcome_detail=f"Atomic file write failed: {str(e)}"
                )
                raise PersistenceError("Failed to write output files atomically") from e

        # Atomic ledger save
        try:
            save_ledger(ledger_path, ledger)
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            log_structured(
                correlation_id=correlation_id,
                step="save_ledger",
                outcome=DNAStatus.ERROR,
                latency_ms=latency_ms,
                actor_id=actor_id,
                outcome_detail=f"Ledger save failed: {str(e)}"
            )
            raise PersistenceError("Failed to save ledger atomically") from e

    if error_occurred:
        latency_ms = int((time.time() - start_time) * 1000)
        log_structured(
            correlation_id=correlation_id,
            step="end",
            outcome=DNAStatus.ERROR,
            latency_ms=latency_ms,
            actor_id=actor_id,
            outcome_detail=f"Processing error in batch: {str(processing_exception)}"
        )
        raise processing_exception

    latency_ms = int((time.time() - start_time) * 1000)
    log_structured(
        correlation_id=correlation_id,
        step="end",
        outcome=DNAStatus.SUCCESS,
        latency_ms=latency_ms,
        actor_id=actor_id,
        outcome_detail=f"Batch processed. {new_processed_count} new DNA strings added."
    )
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    return BatchResult(DNAStatus.SUCCESS, new_processed_count)

main = run_batch

if __name__ == '__main__':
    main()
