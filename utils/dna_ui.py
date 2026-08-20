#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

HEAT_PER_SEQUENCE = 2.0
LOCKOUT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input files fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when core heat reaches or exceeds the thermal lockout threshold."""
    def __init__(self, message="Thermal Overload", refusal_reason="Thermal Lockout", consequence="Heat Accumulation", hint="Wait for dissipation. The system is indifferent to your deadlines."):
        super().__init__(message)
        self.refusal_reason = refusal_reason
        self.consequence = consequence
        self.hint = hint

class PersistenceError(DNAProcessingError):
    """Base class for persistence failures."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger file fails due to corruption."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file writes fail."""
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

def log_structured(timestamp, correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    payload = {
        "timestamp": timestamp,
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(payload)}")

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger file: {ledger_path}") from e

        if isinstance(data, dict):
            if "ledger" not in data:
                # Legacy flat layout compatibility
                now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                return {
                    "ledger": data,
                    "system_state": {
                        "core_heat": 0.0,
                        "last_processed_timestamp": now_str
                    }
                }
            return data
        else:
            raise LedgerLoadError(f"Invalid ledger schema in {ledger_path}")

    now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {
        "ledger": {},
        "system_state": {
            "core_heat": 0.0,
            "last_processed_timestamp": now_str
        }
    }

def save_ledger(ledger_path, ledger_data):
    ledger_dir = os.path.dirname(ledger_path)
    ensure_folder(ledger_dir)
    try:
        with tempfile.TemporaryDirectory(dir=ledger_dir) as tmp_dir:
            tmp_file = os.path.join(tmp_dir, 'ledger.json')
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(ledger_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def write_output_files_atomically(output_folder, parsed_json, csv_rows, all_flattened_keys):
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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


def run_batch(correlation_id=None):
    correlation_id = correlation_id or str(uuid.uuid4())
    actor_id = "batch_parser"

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

    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data.get('ledger', {})
    system_state = ledger_data.get('system_state', {})
    core_heat = float(system_state.get('core_heat', 0.0))
    last_processed_timestamp = system_state.get('last_processed_timestamp')

    now = datetime.datetime.now(datetime.timezone.utc)
    now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_processed_timestamp:
        try:
            last_dt = datetime.datetime.strptime(last_processed_timestamp, '%Y-%m-%dT%H:%M:%SZ')
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = max(0.0, (now - last_dt).total_seconds())
            core_heat = max(0.0, core_heat - elapsed_sec * COOLING_RATE_PER_SEC)
        except ValueError:
            pass

    if core_heat >= LOCKOUT_THRESHOLD:
        log_structured(
            now_str, correlation_id, actor_id, "dna_batch_parse", "check_thermal",
            DNAStatus.REFUSED.value, 0, "N/A", "Thermal Lockout"
        )
        ledger_data['ledger'] = ledger
        ledger_data['system_state'] = {
            'core_heat': core_heat,
            'last_processed_timestamp': now_str
        }
        save_ledger(ledger_path, ledger_data)
        raise ThermalOverloadError(
            message="Thermal Lockout",
            refusal_reason="Thermal Lockout",
            consequence="Heat Accumulation",
            hint="Wait for dissipation. The system is indifferent to your deadlines."
        )

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
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            log_structured(
                now_str, correlation_id, actor_id, "dna_batch_parse", "dedupe_check",
                DNAStatus.SKIPPED.value, 0, idempotency_key, "Duplicate sequence skipped"
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if core_heat >= LOCKOUT_THRESHOLD:
            ledger_data['ledger'] = ledger
            ledger_data['system_state'] = {
                'core_heat': core_heat,
                'last_processed_timestamp': now_str
            }
            if new_processed_count > 0:
                write_output_files_atomically(output_folder, parsed_json, csv_rows, all_flattened_keys)
            save_ledger(ledger_path, ledger_data)
            raise ThermalOverloadError(
                message="Thermal Lockout",
                refusal_reason="Thermal Lockout",
                consequence="Heat Accumulation",
                hint="Wait for dissipation. The system is indifferent to your deadlines."
            )

        core_heat += HEAT_PER_SEQUENCE
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
        new_processed_count += 1
        log_structured(
            now_str, correlation_id, actor_id, "dna_batch_parse", "parse_sequence",
            outcome, latency_ms, idempotency_key, f"core_heat={core_heat}"
        )

        if core_heat >= LOCKOUT_THRESHOLD:
            ledger_data['ledger'] = ledger
            ledger_data['system_state'] = {
                'core_heat': core_heat,
                'last_processed_timestamp': now_str
            }
            if new_processed_count > 0:
                write_output_files_atomically(output_folder, parsed_json, csv_rows, all_flattened_keys)
            save_ledger(ledger_path, ledger_data)
            raise ThermalOverloadError(
                message="Thermal Lockout",
                refusal_reason="Thermal Lockout",
                consequence="Heat Accumulation",
                hint="Wait for dissipation. The system is indifferent to your deadlines."
            )

    ledger_data['ledger'] = ledger
    ledger_data['system_state'] = {
        'core_heat': core_heat,
        'last_processed_timestamp': now_str
    }
    save_ledger(ledger_path, ledger_data)

    if new_processed_count > 0:
        write_output_files_atomically(output_folder, parsed_json, csv_rows, all_flattened_keys)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    print(f"     JSON -> {json_output_path}")
    print(f"     CSV  -> {csv_output_path}")

main = run_batch

if __name__ == '__main__':
    run_batch()
