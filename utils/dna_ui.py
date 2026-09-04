#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from datetime import datetime, timezone
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
    """Raised when reading input DNA sequences file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger fails due to corruption or IO error."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing or moving output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system is in thermal lockout."""
    pass

def log_structured(event_data):
    """Emits structured telemetry JSON logs prefixed with JSON_LOG:"""
    now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_entry = {
        'timestamp': event_data.get('timestamp', now_utc),
        'correlation_id': event_data.get('correlation_id', ''),
        'actor_id': event_data.get('actor_id', 'batch_parser'),
        'chain_name': event_data.get('chain_name', 'dna_batch_parse'),
        'step': event_data.get('step', 'process'),
        'outcome': event_data.get('outcome', DNAStatus.SUCCESS.value),
        'latency_ms': event_data.get('latency_ms', 0),
        'idempotency_key': event_data.get('idempotency_key', ''),
        'outcome_detail': event_data.get('outcome_detail', '')
    }
    print(f"JSON_LOG:{json.dumps(log_entry)}")

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
                if not isinstance(data, dict):
                    raise LedgerLoadError(f"Corrupted ledger structure in {ledger_path}")
                return data
        except Exception as e:
            if isinstance(e, LedgerLoadError):
                raise
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}") from e
    return {}

def save_ledger(ledger_path, data):
    try:
        dirname = os.path.dirname(ledger_path) or '.'
        with tempfile.TemporaryDirectory(dir=dirname) as tmp_dir:
            tmp_file = os.path.join(tmp_dir, 'ledger.json')
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None, actor_id='batch_parser'):
    start_time = time.time()
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    log_structured({
        'correlation_id': correlation_id,
        'actor_id': actor_id,
        'chain_name': 'dna_batch_parse',
        'step': 'start',
        'outcome': 'success',
        'latency_ms': 0,
        'outcome_detail': 'Batch run started'
    })

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

    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    full_ledger_data = load_ledger(ledger_path)

    # Separate ledger and system_state
    if isinstance(full_ledger_data, dict) and 'ledger' in full_ledger_data:
        ledger = full_ledger_data['ledger']
        system_state = full_ledger_data.get('system_state', {})
    else:
        ledger = full_ledger_data
        system_state = {}

    core_heat = system_state.get('core_heat', 0.0)
    last_processed_timestamp = system_state.get('last_processed_timestamp', None)

    # Calculate dissipation (0.5 heat per second)
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_processed_timestamp:
        try:
            last_dt = datetime.strptime(last_processed_timestamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            elapsed_seconds = (now_dt - last_dt).total_seconds()
            if elapsed_seconds > 0:
                core_heat = max(0.0, core_heat - (elapsed_seconds * 0.5))
        except ValueError:
            pass

    # Check thermal lockout
    LOCKOUT_THRESHOLD = 10.0
    if core_heat >= LOCKOUT_THRESHOLD:
        log_structured({
            'correlation_id': correlation_id,
            'actor_id': actor_id,
            'chain_name': 'dna_batch_parse',
            'step': 'thermal_check',
            'outcome': DNAStatus.REFUSED.value,
            'latency_ms': int((time.time() - start_time) * 1000),
            'outcome_detail': 'Thermal Lockout'
        })
        print("Thermal Lockout")
        print("Wait for dissipation. The system is indifferent to your deadlines.")
        raise ThermalOverloadError("Thermal Lockout: Wait for dissipation. The system is indifferent to your deadlines.")

    # Load existing output JSON
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

    # Load existing output CSV
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
            terminal_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
            log_structured({
                'correlation_id': correlation_id,
                'actor_id': actor_id,
                'chain_name': 'dna_batch_parse',
                'step': 'deduplication',
                'outcome': DNAStatus.SKIPPED.value,
                'idempotency_key': idempotency_key,
                'outcome_detail': f"Skipped already processed key with status {terminal_outcome}"
            })
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Check heat before processing each item
        if core_heat >= LOCKOUT_THRESHOLD:
            log_structured({
                'correlation_id': correlation_id,
                'actor_id': actor_id,
                'chain_name': 'dna_batch_parse',
                'step': 'thermal_check',
                'outcome': DNAStatus.REFUSED.value,
                'idempotency_key': idempotency_key,
                'latency_ms': int((time.time() - start_time) * 1000),
                'outcome_detail': 'Thermal Lockout'
            })
            print("Thermal Lockout")
            print("Wait for dissipation. The system is indifferent to your deadlines.")
            # Save current state before throwing overload error
            full_ledger = {
                'ledger': ledger,
                'system_state': {
                    'core_heat': core_heat,
                    'last_processed_timestamp': now_str
                }
            }
            save_ledger(ledger_path, full_ledger)
            raise ThermalOverloadError("Thermal Lockout: Wait for dissipation. The system is indifferent to your deadlines.")

        item_start = time.time()
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

            flat = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            }
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        item_latency = int((time.time() - item_start) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        new_processed_count += 1

        if outcome == DNAStatus.SUCCESS.value:
            core_heat += 2.0
            print("Heat Accumulation")

        log_structured({
            'correlation_id': correlation_id,
            'actor_id': actor_id,
            'chain_name': 'dna_batch_parse',
            'step': 'parse_item',
            'outcome': outcome,
            'latency_ms': item_latency,
            'idempotency_key': idempotency_key,
            'outcome_detail': f"Processed sequence with status {outcome}"
        })

    # ATOMIC WRITE PATTERN:
    # Rewrite output files ONLY if new_processed_count > 0
    if new_processed_count > 0:
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

        # Save structured ledger
        full_ledger = {
            'ledger': ledger,
            'system_state': {
                'core_heat': core_heat,
                'last_processed_timestamp': now_str
            }
        }
        save_ledger(ledger_path, full_ledger)

    total_latency = int((time.time() - start_time) * 1000)
    log_structured({
        'correlation_id': correlation_id,
        'actor_id': actor_id,
        'chain_name': 'dna_batch_parse',
        'step': 'end',
        'outcome': DNAStatus.SUCCESS.value,
        'latency_ms': total_latency,
        'outcome_detail': f"Processed {new_processed_count} new sequences"
    })

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

main = run_batch

if __name__ == '__main__':
    main()
