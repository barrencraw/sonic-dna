#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import datetime
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

UI_MESSAGES = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

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
    """Raised when reading input file fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when core heat meets or exceeds lockout threshold."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when persisting output files or ledger fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing the ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file writes fail."""
    pass


def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_entry = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "",
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name or "dna_batch_parser",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "",
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
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}") from e

        if isinstance(data, dict) and 'ledger' in data:
            ledger = data.get('ledger', {})
            system_state = data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})
            return ledger, system_state
        elif isinstance(data, dict):
            # Legacy flat ledger structure
            return data, {'core_heat': 0.0, 'last_processed_timestamp': None}

    return {}, {'core_heat': 0.0, 'last_processed_timestamp': None}


def save_ledger(ledger_path, ledger, system_state):
    data = {
        'ledger': ledger,
        'system_state': system_state
    }
    try:
        tmp_dir = os.path.dirname(os.path.abspath(ledger_path))
        ensure_folder(tmp_dir)
        with tempfile.NamedTemporaryFile('w', dir=tmp_dir, delete=False, encoding='utf-8') as tf:
            json.dump(data, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_name = tf.name
        os.replace(tmp_name, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e


def run_batch(correlation_id=None, actor_id='batch_parser'):
    if correlation_id is None:
        correlation_id = uuid.uuid4().hex

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger, system_state = load_ledger(ledger_path)
    import copy
    initial_ledger = copy.deepcopy(ledger)

    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed = max(0.0, (now_utc - last_time).total_seconds())
            core_heat = max(0.0, core_heat - 0.5 * elapsed)
        except Exception:
            pass

    # Load existing JSON output
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                data = json.load(jf)
                if isinstance(data, list):
                    parsed_json = data
        except Exception:
            parsed_json = []

    # Load existing CSV rows
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
        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(correlation_id, actor_id, 'dna_batch_parser', 'deduplication_check', DNAStatus.SKIPPED.value, 0, idempotency_key, 'dedupe_hit')
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if core_heat >= 10.0:
            system_state['core_heat'] = core_heat
            system_state['last_processed_timestamp'] = now_str
            save_ledger(ledger_path, initial_ledger, system_state)
            log_structured(correlation_id, actor_id, 'dna_batch_parser', 'heat_check', DNAStatus.REFUSED.value, 0, idempotency_key, UI_MESSAGES['refusal_reason'])
            raise ThermalOverloadError(f"{UI_MESSAGES['refusal_reason']}: {UI_MESSAGES['next_action_hint']}")

        start_time = time.time()
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
            core_heat += 2.0

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

        latency_ms = int((time.time() - start_time) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        log_structured(correlation_id, actor_id, 'dna_batch_parser', 'parse_sequence', outcome, latency_ms, idempotency_key, UI_MESSAGES['consequence_applied'] if outcome == DNAStatus.SUCCESS.value else 'parse_error')
        new_processed_count += 1

    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = now_str

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger, system_state)

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
    else:
        # Save updated thermal system_state even if no new sequences were processed
        save_ledger(ledger_path, ledger, system_state)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")


main = run_batch

if __name__ == '__main__':
    main()
