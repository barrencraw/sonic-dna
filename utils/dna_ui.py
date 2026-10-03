#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys
CONSEQUENCE_APPLIED = "Heat Accumulation"
REFUSAL_REASON = "Thermal Lockout"
NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# Systemic Parameters
HEAT_PER_SEQUENCE = 2.0
LOCKOUT_THRESHOLD = 10.0
DISSIPATION_RATE = 0.5

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
    """Raised when loading ledger fails or is corrupted."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when core heat exceeds safety threshold."""
    pass

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
                    data = {}
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger file: {ledger_path}") from e
    else:
        data = {}

    if 'ledger' in data and 'system_state' in data:
        ledger = data['ledger']
        system_state = data['system_state']
    else:
        ledger = data
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}

    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')
    if last_time_str:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if last_time_str.endswith('Z'):
                last_time_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            else:
                last_time_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (now_utc - last_time_dt).total_seconds())
            dissipation = elapsed_seconds * DISSIPATION_RATE
            core_heat = max(0.0, core_heat - dissipation)
        except Exception:
            pass

    system_state['core_heat'] = core_heat
    return {'ledger': ledger, 'system_state': system_state}

def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def log_structured(correlation_id=None, actor_id='batch_parser', chain_name='dna_batch', step='process', outcome='success', latency_ms=0, idempotency_key=None, outcome_detail=None):
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    payload = {
        'timestamp': now_str,
        'correlation_id': correlation_id or '',
        'actor_id': actor_id,
        'chain_name': chain_name,
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key or '',
        'outcome_detail': outcome_detail or ''
    }
    print(f"JSON_LOG: {json.dumps(payload)}")

def main(correlation_id=None):
    start_time = time.time()
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

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

    full_ledger_data = load_ledger(ledger_path)
    ledger = full_ledger_data['ledger']
    system_state = full_ledger_data['system_state']
    core_heat = float(system_state.get('core_heat', 0.0))

    initial_ledger = dict(ledger)

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
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
    thermal_overload_occurred = False

    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key].get('terminal_outcome')}")
            log_structured(
                correlation_id=correlation_id,
                step='deduplicate',
                outcome=DNAStatus.SKIPPED,
                idempotency_key=idempotency_key,
                outcome_detail='already_processed'
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if core_heat + HEAT_PER_SEQUENCE > LOCKOUT_THRESHOLD:
            print(f"[Thermal] {CONSEQUENCE_APPLIED}: core_heat={core_heat:.2f} + {HEAT_PER_SEQUENCE} > threshold {LOCKOUT_THRESHOLD}")
            print(f"[Thermal] {REFUSAL_REASON}: {NEXT_ACTION_HINT}")
            thermal_overload_occurred = True
            log_structured(
                correlation_id=correlation_id,
                step='thermal_check',
                outcome=DNAStatus.REFUSED,
                idempotency_key=idempotency_key,
                outcome_detail=REFUSAL_REASON
            )
            break

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
            core_heat += HEAT_PER_SEQUENCE

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

        now_timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_timestamp
        }
        new_processed_count += 1
        log_structured(
            correlation_id=correlation_id,
            step='parse_sequence',
            outcome=outcome,
            idempotency_key=idempotency_key,
            outcome_detail=f"core_heat={core_heat:.2f}"
        )

    now_utc_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    if thermal_overload_occurred:
        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = now_utc_str
        save_ledger(ledger_path, {'ledger': initial_ledger, 'system_state': system_state})
        raise ThermalOverloadError(REFUSAL_REASON)

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

        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = now_utc_str
        save_ledger(ledger_path, {'ledger': ledger, 'system_state': system_state})

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

run_batch = main

if __name__ == '__main__':
    main()
