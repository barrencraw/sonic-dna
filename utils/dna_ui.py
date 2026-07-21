#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import datetime
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

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path) -> list[str]:
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
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def log_structured(
    step: str,
    outcome: str,
    latency_ms: int = 0,
    correlation_id: str = "orchestrator-session",
    idempotency_key: str = None,
    outcome_detail: str = None,
    actor_id: str = "dna_orchestrator",
    chain_name: str = "dna_batch_parser"
):
    """
    Emits structured JSON logs with the JSON_LOG: prefix.
    """
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def process_single_dna(dna_sequence: str, calculator: DNACalculator) -> tuple[DNAStatus, dict | str]:
    """
    Encapsulates DNA string parsing to classify outcomes into explicit DNAStatus enum values.
    Returns (status, values_dict) on success, or (status, error_message) on failure.
    """
    try:
        result = calculator.parse(dna_sequence)
        return DNAStatus.SUCCESS, result
    except RuleParseError as e:
        return DNAStatus.ERROR, str(e)

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = "orchestrator-session"

    log_structured(
        step="batch_started",
        outcome="success",
        correlation_id=correlation_id
    )

    start_time_ns = time.perf_counter_ns()

    # Determine file paths
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
            step="batch_failed",
            outcome="error",
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
            step="batch_failed",
            outcome="error",
            outcome_detail=f"Could not load rules: {str(e)}",
            correlation_id=correlation_id
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            step="batch_failed",
            outcome="error",
            outcome_detail=f"Failed to read input file: {str(e)}",
            correlation_id=correlation_id
        )
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        log_structured(
            step="batch_completed",
            outcome="success",
            outcome_detail="No DNA sequences found in toSequence.txt",
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
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(
                step="item_deduplicated",
                outcome="skipped",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}"
            )
            continue

        item_start_time = time.perf_counter_ns()
        status, parse_result = process_single_dna(dna_sequence, calculator)
        item_latency_ms = (time.perf_counter_ns() - item_start_time) // 1_000_000

        if status == DNAStatus.SUCCESS:
            entry = {
                'dna': dna_sequence,
                'rule': parse_result['rule'],
                'parsed': parse_result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(parse_result['rule'], parse_result['values'])
            flat['dna'] = dna_sequence
            flat['rule'] = parse_result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"
            outcome_detail = f"Successfully parsed rule {parse_result['rule']}"
        else:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_sequence,
                'error': parse_result
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_sequence, 'error': parse_result}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "error"
            outcome_detail = parse_result

        # Update ledger and new processed count inside the loop
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        new_processed_count += 1

        log_structured(
            step="item_processed",
            outcome=outcome,
            latency_ms=item_latency_ms,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )

    # Save outputs if any new items were processed
    if new_processed_count > 0:
        # Atomic write pattern
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
                    step="batch_failed",
                    outcome="error",
                    outcome_detail=f"Atomic write persistence error: {str(e)}",
                    correlation_id=correlation_id
                )
                raise PersistenceError("Failed to write output files atomically") from e

        # Save ledger
        try:
            save_ledger(ledger_path, ledger)
        except Exception as e:
            log_structured(
                step="batch_failed",
                outcome="error",
                outcome_detail=f"Ledger persistence error: {str(e)}",
                correlation_id=correlation_id
            )
            raise PersistenceError(f"Failed to save ledger: {str(e)}") from e

    batch_latency_ms = (time.perf_counter_ns() - start_time_ns) // 1_000_000
    log_structured(
        step="batch_completed",
        outcome="success",
        latency_ms=batch_latency_ms,
        correlation_id=correlation_id,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    main()
