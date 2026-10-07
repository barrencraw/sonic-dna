#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import datetime
import tempfile
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
    """Raised when reading input file fails."""
    pass


class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when reading or parsing ledger file fails."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving ledger file fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when atomic write or rename fails."""
    pass


def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail=""):
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "batch_parser",
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
            raise LedgerLoadError(f"Corrupted or invalid ledger at {ledger_path}") from e
    return {}


def save_ledger(ledger_path, ledger):
    target_dir = os.path.dirname(os.path.abspath(ledger_path))
    ensure_folder(target_dir)
    try:
        with tempfile.NamedTemporaryFile('w', dir=target_dir, delete=False, encoding='utf-8') as tmpf:
            json.dump(ledger, tmpf, indent=2)
            tmpf.flush()
            os.fsync(tmpf.fileno())
            tmp_name = tmpf.name
        os.replace(tmp_name, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger atomically to {ledger_path}") from e


def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    if not correlation_id:
        correlation_id = uuid.uuid4().hex

    chain_name = "dna_batch_parsing"
    log_structured(correlation_id, actor_id, chain_name, "start", DNAStatus.SUCCESS, 0.0, "batch_start", "Batch DNA processing initiated")

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
        log_structured(correlation_id, actor_id, chain_name, "end", DNAStatus.REFUSED, (time.time() - start_time) * 1000, "none", f"Input file not found: {input_file}")
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, actor_id, chain_name, "end", DNAStatus.REFUSED, (time.time() - start_time) * 1000, "none", f"Rule load error: {e}")
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        log_structured(correlation_id, actor_id, chain_name, "end", DNAStatus.SUCCESS, (time.time() - start_time) * 1000, "none", "No DNA sequences found in input file")
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger_data = load_ledger(ledger_path)
    if isinstance(ledger_data, dict) and 'ledger' in ledger_data:
        ledger = ledger_data['ledger']
    elif isinstance(ledger_data, dict):
        ledger = ledger_data
    else:
        ledger = {}

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                data = json.load(jf)
                if isinstance(data, list):
                    parsed_json = data
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

    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS)
            log_structured(
                correlation_id, actor_id, chain_name, "parse_sequence",
                DNAStatus.SKIPPED, (time.time() - start_time) * 1000, idempotency_key,
                f"Dedupe hit. Key already processed with outcome: {term_outcome}"
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            continue

        seq_start = time.time()
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

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS
            detail = "Parsed successfully"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"
            detail = f"RuleParseError: {e}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        new_processed_count += 1

        log_structured(
            correlation_id, actor_id, chain_name, "parse_sequence",
            outcome if outcome == DNAStatus.SUCCESS else DNAStatus.ERROR,
            (time.time() - seq_start) * 1000, idempotency_key, detail
        )

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
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
                log_structured(
                    correlation_id, actor_id, chain_name, "persist_outputs",
                    DNAStatus.ERROR, (time.time() - start_time) * 1000, "batch", f"AtomicWriteError: {e}"
                )
                raise AtomicWriteError("Failed to write output files atomically") from e

        # Save ledger
        if isinstance(ledger_data, dict) and 'ledger' in ledger_data:
            ledger_data['ledger'] = ledger
            save_ledger(ledger_path, ledger_data)
        else:
            save_ledger(ledger_path, ledger)

    latency = (time.time() - start_time) * 1000
    log_structured(
        correlation_id, actor_id, chain_name, "end",
        DNAStatus.SUCCESS, latency, "batch_end",
        f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )
    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")


main = run_batch


if __name__ == '__main__':
    main()
