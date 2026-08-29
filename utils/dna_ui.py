#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
import uuid
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
    """Raised when reading input file fails."""
    pass


class ThermalOverloadError(DNAProcessingError):
    """Raised when system exceeds thermal lockout threshold."""
    pass


class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when loading ledger fails (e.g., corrupt JSON)."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when atomic output file writing fails."""
    pass


HEAT_PER_PARSE = 2.0
COOLING_RATE = 0.5
LOCKOUT_THRESHOLD = 10.0


def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_entry = {
        'timestamp': timestamp,
        'correlation_id': correlation_id or str(uuid.uuid4()),
        'actor_id': actor_id or 'batch_parser',
        'chain_name': chain_name,
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail
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
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e

        if isinstance(data, dict) and 'ledger' in data:
            ledger = data.get('ledger', {})
            system_state = data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})
        elif isinstance(data, dict):
            ledger = data
            system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}
        else:
            ledger = {}
            system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}
        return {'ledger': ledger, 'system_state': system_state}
    return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}


def save_ledger(ledger_path, ledger_data):
    try:
        with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(os.path.abspath(ledger_path)), delete=False, encoding='utf-8') as tmp_file:
            json.dump(ledger_data, tmp_file, indent=2)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_name = tmp_file.name
        os.replace(tmp_name, ledger_path)
    except Exception as e:
        if 'tmp_name' in locals() and os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e


def compute_heat_decay(current_heat, last_time_str, current_time_dt):
    if not last_time_str or current_heat <= 0.0:
        return max(0.0, current_heat)
    try:
        # Handle UTC timestamp string format '%Y-%m-%dT%H:%M:%SZ' or legacy '%Y-%m-%d %H:%M:%S'
        if 'T' in last_time_str:
            last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
        else:
            last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc)
        elapsed_seconds = max(0.0, (current_time_dt - last_dt).total_seconds())
        decayed = max(0.0, current_heat - (elapsed_seconds * COOLING_RATE))
        return decayed
    except Exception:
        return max(0.0, current_heat)


def run_batch(correlation_id=None, actor_id='batch_parser'):
    start_time = time.time()
    cid = correlation_id or str(uuid.uuid4())
    log_structured(cid, actor_id, 'dna_batch_parsing', 'start', DNAStatus.SUCCESS.value)

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_structured(cid, actor_id, 'dna_batch_parsing', 'end', DNAStatus.SUCCESS.value, int((time.time() - start_time) * 1000))
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(cid, actor_id, 'dna_batch_parsing', 'load_rules', DNAStatus.ERROR.value, outcome_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        log_structured(cid, actor_id, 'dna_batch_parsing', 'end', DNAStatus.SUCCESS.value, int((time.time() - start_time) * 1000))
        return

    full_ledger = load_ledger(ledger_path)
    ledger = full_ledger['ledger']
    system_state = full_ledger['system_state']

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    current_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')
    decayed_heat = compute_heat_decay(current_heat, last_time_str, now_dt)
    system_state['core_heat'] = decayed_heat

    if decayed_heat >= LOCKOUT_THRESHOLD:
        full_ledger['system_state']['last_processed_timestamp'] = now_str
        save_ledger(ledger_path, full_ledger)
        log_structured(cid, actor_id, 'dna_batch_parsing', 'thermal_check', DNAStatus.REFUSED.value,
                       outcome_detail={'reason': 'Thermal Lockout', 'hint': 'Wait for dissipation. The system is indifferent to your deadlines.'})
        raise ThermalOverloadError("Thermal Lockout: Wait for dissipation. The system is indifferent to your deadlines.")

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

    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger:
            existing_outcome = ledger[idempotency_key].get('terminal_outcome')
            if existing_outcome in [DNAStatus.SUCCESS.value, DNAStatus.ERROR.value]:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={existing_outcome}")
                log_structured(cid, actor_id, 'dna_batch_parsing', 'dedupe_check', DNAStatus.SKIPPED.value, idempotency_key=idempotency_key)
                continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if system_state['core_heat'] >= LOCKOUT_THRESHOLD:
            full_ledger['system_state']['last_processed_timestamp'] = now_str
            save_ledger(ledger_path, full_ledger)
            log_structured(cid, actor_id, 'dna_batch_parsing', 'process_sequence', DNAStatus.REFUSED.value,
                           idempotency_key=idempotency_key,
                           outcome_detail={'reason': 'Thermal Lockout', 'hint': 'Wait for dissipation. The system is indifferent to your deadlines.'})
            raise ThermalOverloadError("Thermal Lockout: Wait for dissipation. The system is indifferent to your deadlines.")

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
            system_state['core_heat'] += HEAT_PER_PARSE
            system_state['last_processed_timestamp'] = now_str
            log_structured(cid, actor_id, 'dna_batch_parsing', 'parse_sequence', DNAStatus.SUCCESS.value,
                           idempotency_key=idempotency_key,
                           outcome_detail={'Heat Accumulation': f'+{HEAT_PER_PARSE} heat'})

        except RuleParseError as e:
            entry = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            }
            parsed_json.append(entry)

            flat = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            }
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.ERROR.value
            system_state['last_processed_timestamp'] = now_str
            log_structured(cid, actor_id, 'dna_batch_parsing', 'parse_sequence', DNAStatus.ERROR.value,
                           idempotency_key=idempotency_key,
                           outcome_detail={'error': str(e)})

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count > 0:
        save_ledger(ledger_path, full_ledger)

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

    latency_ms = int((time.time() - start_time) * 1000)
    log_structured(cid, actor_id, 'dna_batch_parsing', 'end', DNAStatus.SUCCESS.value, latency_ms)
    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")


main = run_batch

if __name__ == '__main__':
    main()
