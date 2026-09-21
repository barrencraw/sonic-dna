#!/usr/bin/env python3
import os
import sys
import json
import csv
import time
import uuid
import datetime
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
    """Raised when input file cannot be read."""
    pass


class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when loading ledger fails (e.g. invalid JSON format)."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when atomic output file write fails."""
    pass


def log_structured(correlation_id, step, outcome, latency_ms=0, actor_id="batch_parser", idempotency_key=None, outcome_detail=None, chain_name="dna_batch_parser"):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
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
    print(f"JSON_LOG: {json.dumps(payload)}", flush=True)


def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def read_input_file(input_path):
    """
    Reads input file under data/raw; each line is one DNA sequence.
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
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Corrupted ledger JSON at {ledger_path}") from e
        except Exception as e:
            raise LedgerLoadError(f"Could not load ledger at {ledger_path}") from e
    return {}


def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e


def get_ledger_map(ledger_data):
    if isinstance(ledger_data, dict) and 'ledger' in ledger_data and isinstance(ledger_data['ledger'], dict):
        return ledger_data['ledger']
    if isinstance(ledger_data, dict):
        return ledger_data
    return {}


def run_batch(correlation_id=None, actor_id="batch_parser"):
    correlation_id = correlation_id or str(uuid.uuid4())
    start_batch_time = time.time()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    # Output paths unconditionally defined
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id,
            step="read_input",
            outcome=DNAStatus.ERROR,
            actor_id=actor_id,
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
    log_structured(
        correlation_id,
        step="read_input",
        outcome=DNAStatus.SUCCESS,
        actor_id=actor_id,
        outcome_detail=f"Loaded {len(dna_sequence_list)} DNA sequences"
    )

    if not dna_sequence_list:
        log_structured(
            correlation_id,
            step="batch_complete",
            outcome=DNAStatus.SKIPPED,
            actor_id=actor_id,
            outcome_detail="No DNA sequences found in input file"
        )
        return

    raw_ledger_data = load_ledger(ledger_path)
    ledger_map = get_ledger_map(raw_ledger_data)

    # 1) Load existing JSON output
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                content = json.load(jf)
                if isinstance(content, list):
                    parsed_json = content
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
    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger_map:
            terminal_outcome = ledger_map[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS)
            log_structured(
                correlation_id,
                step="dedupe_check",
                outcome=DNAStatus.SKIPPED,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit. Terminal outcome: {terminal_outcome}"
            )
            continue

        parse_start = time.time()
        try:
            result = calculator.parse(dna_seq)
            latency = int((time.time() - parse_start) * 1000)
            entry = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_seq
            flat['dna_sequence'] = dna_seq
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS

            ledger_map[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1
            log_structured(
                correlation_id,
                step="parse_sequence",
                outcome=outcome,
                latency_ms=latency,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Parsed rule {result['rule']}"
            )

        except RuleParseError as e:
            latency = int((time.time() - parse_start) * 1000)
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

            ledger_map[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1
            log_structured(
                correlation_id,
                step="parse_sequence",
                outcome=outcome,
                latency_ms=latency,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=str(e)
            )

    if new_processed_count > 0:
        # Update raw ledger data if structured, or directly
        if isinstance(raw_ledger_data, dict) and 'ledger' in raw_ledger_data:
            raw_ledger_data['ledger'] = ledger_map
            ledger_to_save = raw_ledger_data
        else:
            ledger_to_save = ledger_map

        save_ledger(ledger_path, ledger_to_save)

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

        log_structured(
            correlation_id,
            step="atomic_write",
            outcome=DNAStatus.SUCCESS,
            actor_id=actor_id,
            outcome_detail=f"Committed {new_processed_count} new entries to disk"
        )
    else:
        log_structured(
            correlation_id,
            step="atomic_write",
            outcome=DNAStatus.SKIPPED,
            actor_id=actor_id,
            outcome_detail="No new DNA sequences processed"
        )

    batch_latency = int((time.time() - start_batch_time) * 1000)
    log_structured(
        correlation_id,
        step="batch_complete",
        outcome=DNAStatus.SUCCESS,
        latency_ms=batch_latency,
        actor_id=actor_id,
        outcome_detail=f"Batch completed. {new_processed_count} new, {len(ledger_map)} total in ledger"
    )


main = run_batch


if __name__ == '__main__':
    main()
