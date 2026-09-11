#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import uuid
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError


class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

    def __str__(self):
        return str(self.value)


class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass


class InputReadError(DNAProcessingError):
    """Raised when reading input sequence file fails."""
    pass


class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass


class PersistenceError(DNAProcessingError):
    """Base class for output or state persistence errors."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when reading or parsing the processed ledger fails."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass


def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    outcome_str = outcome.value if isinstance(outcome, DNAStatus) else str(outcome)
    log_data = {
        "timestamp": ts,
        "correlation_id": correlation_id or "",
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome_str,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")


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
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except Exception as e:
            raise LedgerLoadError(f"Failed to load processed ledger from {ledger_path}: {str(e)}") from e
    return {}


def save_ledger(ledger_path, ledger):
    try:
        tmp_ledger = ledger_path + ".tmp"
        with open(tmp_ledger, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_ledger, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save processed ledger to {ledger_path}: {str(e)}") from e


def run_batch(correlation_id=None, actor_id='batch_parser'):
    start_time = time.time()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    log_structured(correlation_id, actor_id, "dna_batch_parser", "start", "processing", 0, None, "Starting batch execution")

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_structured(correlation_id, actor_id, "dna_batch_parser", "end", DNAStatus.SKIPPED, 0, None, f"Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        log_structured(correlation_id, actor_id, "dna_batch_parser", "end", DNAStatus.SKIPPED, 0, None, "No DNA sequences found")
        return

    ledger = load_ledger(ledger_path)

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
    ledger_dict = ledger.get('ledger', ledger) if isinstance(ledger, dict) else ledger

    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence

        if idempotency_key in ledger_dict:
            outcome_info = ledger_dict[idempotency_key]
            term_outcome = outcome_info.get('terminal_outcome', DNAStatus.SKIPPED) if isinstance(outcome_info, dict) else DNAStatus.SKIPPED
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(correlation_id, actor_id, "dna_batch_parser", "dedupe_check", DNAStatus.SKIPPED, 0, idempotency_key, f"Dedupe hit, previously recorded as {term_outcome}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
        log_structured(correlation_id, actor_id, "dna_batch_parser", "dedupe_check", "processing", 0, idempotency_key, "Dedupe miss, starting processing")

        parse_start = time.time()
        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS
            outcome_detail = "Successfully parsed sequence"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR
            outcome_detail = f"Rule parse error: {str(e)}"

        parse_lat = int((time.time() - parse_start) * 1000)
        log_structured(correlation_id, actor_id, "dna_batch_parser", "parse", outcome, parse_lat, idempotency_key, outcome_detail)

        ts_now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ledger_dict[idempotency_key] = {
            'terminal_outcome': str(outcome),
            'timestamp': ts_now
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count > 0:
        commit_start = time.time()
        log_structured(correlation_id, actor_id, "dna_batch_parser", "commit", "processing", 0, None, f"Committing {new_processed_count} new entries")

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
                raise AtomicWriteError(f"Failed to write output files atomically: {str(e)}") from e

        save_ledger(ledger_path, ledger)
        commit_lat = int((time.time() - commit_start) * 1000)
        log_structured(correlation_id, actor_id, "dna_batch_parser", "commit", DNAStatus.SUCCESS, commit_lat, None, "Atomic write and ledger update successful")

    total_lat = int((time.time() - start_time) * 1000)
    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger_dict)}")
    log_structured(correlation_id, actor_id, "dna_batch_parser", "end", DNAStatus.SUCCESS, total_lat, None, f"Processed {new_processed_count} new sequences")


main = run_batch

if __name__ == '__main__':
    main()
