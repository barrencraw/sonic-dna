#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
from datetime import datetime, timezone
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


class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass


class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass


class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing ledger file fails."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when writing or saving ledger file fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when writing or moving output files atomically fails."""
    pass


def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None):
    """
    Emits structured JSON telemetry logs prefixed with 'JSON_LOG:'.
    """
    log_data = {
        'timestamp': datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        'correlation_id': correlation_id or "unknown",
        'actor_id': actor_id or "batch_parser",
        'chain_name': chain_name or "dna_batch_parsing",
        'step': step,
        'outcome': outcome.value if isinstance(outcome, Enum) else outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")


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
        return dna_sequence_list
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_path}") from e


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
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}


def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e


def run_batch(correlation_id=None, actor_id='batch_parser'):
    start_time = time.time()
    if not correlation_id:
        correlation_id = uuid.uuid4().hex

    chain_name = "dna_batch_parsing"
    log_structured(correlation_id, actor_id, chain_name, "start", "processing")

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_structured(correlation_id, actor_id, chain_name, "end", DNAStatus.ERROR, outcome_detail=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    rules_path = os.path.join(project_root, 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_path)
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {rules_path}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        log_structured(correlation_id, actor_id, chain_name, "end", DNAStatus.SUCCESS, outcome_detail="No DNA sequences found")
        return

    ledger = load_ledger(ledger_path)
    # Support structured vs flat ledger
    ledger_dict = ledger.get('ledger', ledger) if isinstance(ledger, dict) else {}

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
        idempotency_key = dna_seq
        if idempotency_key in ledger_dict:
            term_outcome = ledger_dict[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(
                correlation_id, actor_id, chain_name, "parse_sequence",
                DNAStatus.SKIPPED, idempotency_key=idempotency_key, outcome_detail="Deduplicated"
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_seq)
            entry = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_seq
            flat['dna_sequence'] = dna_seq
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value

        except RuleParseError as e:
            entry = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            }
            parsed_json.append(entry)
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        ledger_dict[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        if isinstance(ledger, dict) and 'ledger' in ledger:
            ledger['ledger'] = ledger_dict

        new_processed_count += 1
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        log_structured(
            correlation_id, actor_id, chain_name, "parse_sequence",
            outcome, idempotency_key=idempotency_key, outcome_detail=f"Outcome: {outcome}"
        )

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger)

        # Atomic Write Pattern
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

        log_structured(correlation_id, actor_id, chain_name, "commit_outputs", DNAStatus.SUCCESS, outcome_detail=f"Committed {new_processed_count} new sequences")

    latency = int((time.time() - start_time) * 1000)
    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger_dict)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

    log_structured(correlation_id, actor_id, chain_name, "end", DNAStatus.SUCCESS, latency_ms=latency, outcome_detail=f"Processed {new_processed_count} sequences")


main = run_batch


if __name__ == '__main__':
    run_batch()
