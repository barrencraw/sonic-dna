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
    """Raised when input file cannot be read."""
    pass


class ThermalOverloadError(DNAProcessingError):
    """Raised when system thermal lockout threshold is reached."""
    def __init__(
        self,
        message="Thermal Lockout",
        consequence="Heat Accumulation",
        hint="Wait for dissipation. The system is indifferent to your deadlines."
    ):
        super().__init__(message)
        self.consequence = consequence
        self.refusal_reason = message
        self.next_action_hint = hint


class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when ledger file exists but is corrupted."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass


def log_structured(correlation_id=None, actor_id="batch_parser", chain_name="dna_batch_parser",
                   step="process", outcome=DNAStatus.SUCCESS.value, latency_ms=0,
                   idempotency_key=None, outcome_detail=None):
    log_data = {
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'correlation_id': correlation_id or str(uuid.uuid4()),
        'actor_id': actor_id or 'batch_parser',
        'chain_name': chain_name or 'dna_batch_parser',
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail or {}
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
                    raise LedgerLoadError(f"Ledger file at {ledger_path} is not a valid JSON object.")
                return data
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}: {e}") from e
        except Exception as e:
            if isinstance(e, LedgerLoadError):
                raise
            raise PersistenceError(f"Failed to read ledger file at {ledger_path}: {e}") from e
    return {}


def save_ledger(ledger_path, ledger_data):
    try:
        dir_name = os.path.dirname(ledger_path) or '.'
        ensure_folder(dir_name)
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
            json.dump(ledger_data, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name
        os.replace(temp_name, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e


HEAT_PER_SEQUENCE = 2.0
LOCKOUT_THRESHOLD = 10.0
COOLING_RATE = 0.5  # heat units per second


def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    start_time = time.time()
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    raw_ledger_data = load_ledger(ledger_path)
    if 'ledger' in raw_ledger_data and isinstance(raw_ledger_data['ledger'], dict):
        ledger_entries = raw_ledger_data['ledger']
        system_state = raw_ledger_data.get('system_state', {})
    else:
        ledger_entries = raw_ledger_data
        system_state = {}

    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')

    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_time_str:
        try:
            if last_time_str.endswith('Z'):
                last_dt = datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            else:
                last_dt = datetime.fromisoformat(last_time_str)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
            elapsed_seconds = (now_utc - last_dt).total_seconds()
            if elapsed_seconds > 0:
                dissipation = elapsed_seconds * COOLING_RATE
                core_heat = max(0.0, core_heat - dissipation)
        except Exception:
            pass

    # Load existing JSON output
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
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
        if idempotency_key in ledger_entries:
            terminal_outcome = ledger_entries[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
            log_structured(
                correlation_id=correlation_id,
                actor_id='batch_parser',
                chain_name='dna_batch_parser',
                step='deduplication',
                outcome=DNAStatus.SKIPPED.value,
                idempotency_key=idempotency_key,
                outcome_detail={'message': 'Sequence already processed in ledger'}
            )
            continue

        if core_heat + HEAT_PER_SEQUENCE > LOCKOUT_THRESHOLD:
            # Thermal lockout reached!
            updated_system_state = {
                'core_heat': core_heat,
                'last_processed_timestamp': now_iso
            }
            full_ledger_data = {
                'ledger': ledger_entries,
                'system_state': updated_system_state
            }
            save_ledger(ledger_path, full_ledger_data)

            log_structured(
                correlation_id=correlation_id,
                actor_id='batch_parser',
                chain_name='dna_batch_parser',
                step='thermal_check',
                outcome=DNAStatus.REFUSED.value,
                idempotency_key=idempotency_key,
                outcome_detail={
                    'consequence': 'Heat Accumulation',
                    'refusal_reason': 'Thermal Lockout',
                    'next_action_hint': 'Wait for dissipation. The system is indifferent to your deadlines.',
                    'core_heat': core_heat
                }
            )

            raise ThermalOverloadError(
                message="Thermal Lockout",
                consequence="Heat Accumulation",
                hint="Wait for dissipation. The system is indifferent to your deadlines."
            )

        core_heat += HEAT_PER_SEQUENCE

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

        ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_iso
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    updated_system_state = {
        'core_heat': core_heat,
        'last_processed_timestamp': now_iso
    }
    full_ledger_data = {
        'ledger': ledger_entries,
        'system_state': updated_system_state
    }

    save_ledger(ledger_path, full_ledger_data)

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
                raise AtomicWriteError(f"Failed to write output files atomically: {e}") from e

    latency_ms = int((time.time() - start_time) * 1000)
    log_structured(
        correlation_id=correlation_id,
        actor_id='batch_parser',
        chain_name='dna_batch_parser',
        step='batch_complete',
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=latency_ms,
        outcome_detail={'processed_count': new_processed_count, 'core_heat': core_heat}
    )

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger_entries)}")
    print(f"     JSON -> {json_output_path}")
    print(f"     CSV  -> {csv_output_path}")


main = run_batch

if __name__ == '__main__':
    main()
