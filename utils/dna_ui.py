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

class InputReadError(DNAProcessingError):
    """Raised when reading input DNA sequences fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when core heat exceeds safety lockout threshold."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence and writing output errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing ledger file fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass

UI_MESSAGES = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

def log_structured(timestamp, correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    log_entry = {
        "timestamp": timestamp,
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": str(outcome),
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": str(outcome_detail)
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
    dna_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

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
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}: {e}") from e

        if isinstance(data, dict):
            if 'ledger' in data and 'system_state' in data:
                return data
            else:
                # Legacy flat ledger layout
                return {
                    'ledger': data,
                    'system_state': {
                        'core_heat': 0.0,
                        'last_processed_timestamp': None
                    }
                }
        else:
            raise LedgerLoadError(f"Invalid ledger format in {ledger_path}")

    return {
        'ledger': {},
        'system_state': {
            'core_heat': 0.0,
            'last_processed_timestamp': None
        }
    }

def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e

def run_batch(correlation_id=None, actor_id='batch_parser'):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    chain_name = "dna_batch_parse"
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

    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger_full = load_ledger(ledger_path)
    ledger = ledger_full.get('ledger', {})
    system_state = ledger_full.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})

    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp', None)

    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_time_str:
        try:
            if 'T' in last_time_str:
                last_dt = datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            else:
                last_dt = datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            elapsed_sec = (now_utc - last_dt).total_seconds()
            if elapsed_sec > 0:
                core_heat = max(0.0, core_heat - 0.5 * elapsed_sec)
        except Exception:
            pass

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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            term = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term}")
            now_log = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            log_structured(now_log, correlation_id, actor_id, chain_name, "deduplicate", DNAStatus.SKIPPED, 0, idempotency_key, f"dedupe_hit: {term}")
            continue

        if core_heat >= 10.0:
            now_log = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            log_structured(now_log, correlation_id, actor_id, chain_name, "thermal_check", DNAStatus.REFUSED, 0, idempotency_key, UI_MESSAGES["refusal_reason"])

            ledger_full['system_state'] = {'core_heat': core_heat, 'last_processed_timestamp': now_iso}
            save_ledger(ledger_path, ledger_full)

            raise ThermalOverloadError(f"{UI_MESSAGES['refusal_reason']} - Core Heat: {core_heat:.1f} (>= 10.0 threshold). {UI_MESSAGES['next_action_hint']}")

        step_start = time.time()
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'dna_sequence': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['dna_sequence'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.SUCCESS
            core_heat += 2.0
            outcome_detail = f"{UI_MESSAGES['consequence_applied']}: +2.0 heat (total {core_heat:.1f})"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'dna_sequence': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.ERROR
            outcome_detail = f"error: {str(e)}"

        latency_ms = int((time.time() - step_start) * 1000)
        now_log = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        log_structured(now_log, correlation_id, actor_id, chain_name, "parse_sequence", outcome, latency_ms, idempotency_key, outcome_detail)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_iso
        }
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
                raise AtomicWriteError(f"Failed to write output files atomically: {e}") from e

        ledger_full['ledger'] = ledger
        ledger_full['system_state'] = {
            'core_heat': core_heat,
            'last_processed_timestamp': now_iso
        }
        save_ledger(ledger_path, ledger_full)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}. Core Heat: {core_heat:.1f}")

main = run_batch

if __name__ == '__main__':
    run_batch()
