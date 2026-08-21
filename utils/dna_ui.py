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

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

    def __str__(self):
        return self.value

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input DNA file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when ledger file exists but cannot be loaded/parsed."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when ledger cannot be saved atomically."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing or moving output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when the system enters thermal lockout due to fatigue."""
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
                return json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Corrupted or unreadable ledger file: {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger_data):
    tmp_dir = os.path.dirname(ledger_path) or '.'
    try:
        with tempfile.NamedTemporaryFile('w', dir=tmp_dir, delete=False, encoding='utf-8') as tf:
            json.dump(ledger_data, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_name = tf.name
        os.replace(tmp_name, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    log_entry = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'correlation_id': correlation_id or str(uuid.uuid4()),
        'actor_id': actor_id or 'batch_parser',
        'chain_name': chain_name or 'dna_batch_parser',
        'step': step,
        'outcome': str(outcome),
        'latency_ms': round(float(latency_ms), 2),
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_entry)}")

def parse_iso_timestamp(ts_str):
    if not ts_str:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S'):
        try:
            dt = datetime.datetime.strptime(ts_str, fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    return None

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

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

    raw_ledger = load_ledger(ledger_path)
    if isinstance(raw_ledger, dict) and 'ledger' in raw_ledger:
        ledger_map = raw_ledger.get('ledger', {})
        system_state = raw_ledger.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})
    else:
        ledger_map = {}
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}
        if isinstance(raw_ledger, dict):
            for k, v in raw_ledger.items():
                if k != 'system_state':
                    ledger_map[k] = v

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')
    last_dt = parse_iso_timestamp(last_time_str)

    if last_dt is not None:
        elapsed_seconds = max(0.0, (now_dt - last_dt).total_seconds())
        core_heat = max(0.0, core_heat - (elapsed_seconds * 0.5))

    system_state['core_heat'] = core_heat

    # Check thermal fatigue lockout
    if core_heat >= 10.0:
        system_state['last_processed_timestamp'] = now_iso
        ledger_data = {'ledger': ledger_map, 'system_state': system_state}
        for k, v in ledger_map.items():
            ledger_data[k] = v
        save_ledger(ledger_path, ledger_data)
        refused_key = dna_sequence_list[0] if dna_sequence_list else 'unknown'
        log_structured(
            correlation_id=correlation_id,
            actor_id='batch_parser',
            chain_name='dna_batch_parser',
            step='parse_sequence',
            outcome=DNAStatus.REFUSED,
            latency_ms=0.0,
            idempotency_key=refused_key,
            outcome_detail='Thermal Lockout: Wait for dissipation. The system is indifferent to your deadlines.'
        )
        print("[Thermal Lockout] Heat Accumulation exceeds safety threshold. Wait for dissipation. The system is indifferent to your deadlines.")
        raise ThermalOverloadError("Thermal Lockout")

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
        if idempotency_key in ledger_map:
            term_outcome = ledger_map[idempotency_key].get('terminal_outcome', '')
            if str(term_outcome).lower() in [DNAStatus.SUCCESS, DNAStatus.ERROR]:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
                log_structured(
                    correlation_id=correlation_id,
                    actor_id='batch_parser',
                    chain_name='dna_batch_parser',
                    step='parse_sequence',
                    outcome=DNAStatus.SKIPPED,
                    latency_ms=0.0,
                    idempotency_key=idempotency_key,
                    outcome_detail='Already processed in ledger'
                )
                continue

        if core_heat >= 10.0:
            system_state['core_heat'] = core_heat
            system_state['last_processed_timestamp'] = now_iso
            ledger_data = {'ledger': ledger_map, 'system_state': system_state}
            for k, v in ledger_map.items():
                ledger_data[k] = v
            save_ledger(ledger_path, ledger_data)
            log_structured(
                correlation_id=correlation_id,
                actor_id='batch_parser',
                chain_name='dna_batch_parser',
                step='parse_sequence',
                outcome=DNAStatus.REFUSED,
                latency_ms=0.0,
                idempotency_key=idempotency_key,
                outcome_detail='Thermal Lockout: Wait for dissipation. The system is indifferent to your deadlines.'
            )
            print("[Thermal Lockout] Heat Accumulation exceeds safety threshold. Wait for dissipation. The system is indifferent to your deadlines.")
            raise ThermalOverloadError("Thermal Lockout")

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
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

            outcome = DNAStatus.SUCCESS
            detail = 'Successfully parsed DNA sequence'
            core_heat += 2.0
            print(f"[Heat Accumulation] Core heat now {core_heat:.1f}")

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR
            detail = str(e)

        elapsed_ms = (time.time() - start_time) * 1000
        ledger_map[idempotency_key] = {
            'terminal_outcome': str(outcome),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = now_iso

        log_structured(
            correlation_id=correlation_id,
            actor_id='batch_parser',
            chain_name='dna_batch_parser',
            step='parse_sequence',
            outcome=outcome,
            latency_ms=elapsed_ms,
            idempotency_key=idempotency_key,
            outcome_detail=detail
        )
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

        ledger_data = {'ledger': ledger_map, 'system_state': system_state}
        for k, v in ledger_map.items():
            ledger_data[k] = v
        save_ledger(ledger_path, ledger_data)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger_map)}")

main = run_batch

if __name__ == '__main__':
    main()
