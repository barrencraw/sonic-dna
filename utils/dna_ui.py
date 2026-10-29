#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import datetime
import uuid
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

class InputReadError(DNAProcessingError):
    """Raised when input file reading fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when reading or loading ledger file fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass


def log_structured(chain_name, step, outcome, latency_ms=0.0, correlation_id=None, actor_id="batch_parser", idempotency_key=None, outcome_detail=""):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
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
                return json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Ledger file corrupted: {ledger_path}") from e
    return {}


def save_ledger(ledger_path, ledger):
    try:
        dir_name = os.path.dirname(ledger_path)
        if dir_name:
            ensure_folder(dir_name)
        with tempfile.TemporaryDirectory(dir=dir_name or '.') as tmp_dir:
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            with open(tmp_ledger, 'w', encoding='utf-8') as f:
                json.dump(ledger, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_ledger, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger: {e}") from e


def get_ledger_map(ledger_data):
    if isinstance(ledger_data, dict) and 'ledger' in ledger_data and isinstance(ledger_data['ledger'], dict):
        return ledger_data['ledger']
    return ledger_data


def set_ledger_entry(ledger_data, key, entry):
    if isinstance(ledger_data, dict) and 'ledger' in ledger_data and isinstance(ledger_data['ledger'], dict):
        ledger_data['ledger'][key] = entry
    elif isinstance(ledger_data, dict):
        ledger_data[key] = entry


def run_batch(correlation_id=None):
    start_time = time.time()
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    log_structured("dna_batch_parsing", "start", DNAStatus.SUCCESS.value, 0.0, correlation_id, outcome_detail="Starting batch parsing")

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    ensure_folder(raw_folder)
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_structured("dna_batch_parsing", "read_input", DNAStatus.ERROR.value, (time.time() - start_time) * 1000, correlation_id, outcome_detail=f"Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        log_structured("dna_batch_parsing", "read_input", DNAStatus.SUCCESS.value, (time.time() - start_time) * 1000, correlation_id, outcome_detail="No DNA sequences found")
        return

    ledger_data = load_ledger(ledger_path)
    ledger_map = get_ledger_map(ledger_data)

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                content = json.load(jf)
                if isinstance(content, list):
                    parsed_json = content
        except Exception:
            parsed_json = []

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
            entry = ledger_map[idempotency_key]
            outcome_val = entry.get('terminal_outcome', DNAStatus.SKIPPED.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={outcome_val}")
            log_structured("dna_batch_parsing", "dedupe", DNAStatus.SKIPPED.value, (time.time() - start_time) * 1000, correlation_id, idempotency_key=idempotency_key, outcome_detail="Already processed")
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
            outcome_detail = "Successfully parsed"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.ERROR.value
            outcome_detail = f"Parse error: {str(e)}"

        set_ledger_entry(ledger_data, idempotency_key, {
            'terminal_outcome': outcome,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        })

        log_structured("dna_batch_parsing", "parse_sequence", outcome, (time.time() - start_time) * 1000, correlation_id, idempotency_key=idempotency_key, outcome_detail=outcome_detail)
        new_processed_count += 1

    if new_processed_count > 0:
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

        save_ledger(ledger_path, ledger_data)

    duration_ms = (time.time() - start_time) * 1000
    log_structured("dna_batch_parsing", "end", DNAStatus.SUCCESS.value, duration_ms, correlation_id, outcome_detail=f"Processed {new_processed_count} new DNA sequences.")

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(get_ledger_map(ledger_data))}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

main = run_batch

if __name__ == '__main__':
    main()
