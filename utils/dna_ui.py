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

# UI Message Keys
MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# Thermal Constants
HEAT_PER_SEQUENCE = 2.0
HEAT_DISSIPATION_RATE = 0.5  # Heat units decayed per second
LOCKOUT_THRESHOLD = 10.0     # Thermal lockout limit

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

    @property
    def success(self):
        return "success"

    @property
    def error(self):
        return "error"

    @property
    def skipped(self):
        return "skipped"

    @property
    def refused(self):
        return "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading processed ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving processed ledger fails."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file writes fail."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system core heat exceeds safety lockout threshold."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    try:
        dna_sequence_list = []
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
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}") from e

        if isinstance(data, dict):
            if 'ledger' in data:
                ledger_dict = data['ledger']
                system_state = data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})
            else:
                ledger_dict = data
                system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}
            return ledger_dict, system_state
        return {}, {'core_heat': 0.0, 'last_processed_timestamp': None}
    return {}, {'core_heat': 0.0, 'last_processed_timestamp': None}

def save_ledger(ledger_path, ledger_dict, system_state):
    try:
        structured_data = {
            'ledger': ledger_dict,
            'system_state': system_state
        }
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(structured_data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def parse_utc_timestamp(ts_str):
    if not ts_str:
        return None
    try:
        if ts_str.endswith('Z'):
            return datetime.datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.fromisoformat(ts_str)
    except Exception:
        try:
            return datetime.datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc)
        except Exception:
            return None

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        "timestamp": now_str,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None, actor_id="batch_parser"):
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

    ledger, system_state = load_ledger(ledger_path)
    initial_ledger = dict(ledger)

    core_heat = float(system_state.get('core_heat', 0.0))
    last_ts_str = system_state.get('last_processed_timestamp')

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_ts_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Apply thermal decay based on elapsed time
    if last_ts_str:
        last_dt = parse_utc_timestamp(last_ts_str)
        if last_dt:
            elapsed = max(0.0, (now_utc - last_dt).total_seconds())
            core_heat = max(0.0, core_heat - HEAT_DISSIPATION_RATE * elapsed)

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

    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key].get('terminal_outcome')}")
            log_structured(correlation_id, actor_id, "dna_batch_parser", "deduplication_check", DNAStatus.SKIPPED.value, 0, idempotency_key, "Duplicate sequence skipped")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Check thermal lockout threshold before processing
        if core_heat >= LOCKOUT_THRESHOLD:
            current_system_state = {
                'core_heat': core_heat,
                'last_processed_timestamp': now_ts_str
            }
            save_ledger(ledger_path, initial_ledger, current_system_state)
            log_structured(correlation_id, actor_id, "dna_batch_parser", "thermal_check", DNAStatus.REFUSED.value, 0, idempotency_key, MSG_REFUSAL_REASON)
            raise ThermalOverloadError(f"{MSG_REFUSAL_REASON}: Heat level {core_heat:.1f} exceeds limit {LOCKOUT_THRESHOLD}. {MSG_NEXT_ACTION_HINT}")

        start_time = time.time()
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
            outcome = DNAStatus.SUCCESS.value

        except RuleParseError as e:
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            }
            parsed_json.append(entry)

            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        latency_ms = int((time.time() - start_time) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_ts_str
        }
        core_heat += HEAT_PER_SEQUENCE
        last_ts_str = now_ts_str
        new_processed_count += 1

        log_structured(correlation_id, actor_id, "dna_batch_parser", "parse_sequence", outcome, latency_ms, idempotency_key, MSG_CONSEQUENCE_APPLIED)
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome} core_heat={core_heat:.1f}")

    updated_system_state = {
        'core_heat': core_heat,
        'last_processed_timestamp': last_ts_str or now_ts_str
    }

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger, updated_system_state)

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
        save_ledger(ledger_path, ledger, updated_system_state)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Core heat: {core_heat:.1f}. Total in ledger: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    main()
