#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
from enum import Enum
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError


class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"


class DNAProcessingError(Exception):
    """Base exception for all DNA processing errors."""
    pass


class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass


class RuleLoadError(DNAProcessingError):
    """Raised when loading rules fails."""
    pass


class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal limits are exceeded or system is locked out."""
    pass


class PersistenceError(DNAProcessingError):
    """Base exception for persistence errors."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing processed_ledger.json fails."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving processed_ledger.json fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when atomic file writes fail."""
    pass


HEAT_PER_SEQUENCE = 2.0
MAX_HEAT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5

MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."


def log_structured(
    correlation_id=None,
    actor_id="batch_parser",
    chain_name="dna_batch_parsing",
    step="parse",
    outcome="success",
    latency_ms=0,
    idempotency_key=None,
    outcome_detail=None
):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    log_entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
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
                if isinstance(data, dict):
                    if 'ledger' not in data and 'system_state' not in data:
                        return {
                            'ledger': data,
                            'system_state': {
                                'core_heat': 0.0,
                                'last_processed_timestamp': datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                            }
                        }
                    return data
                return {
                    'ledger': {},
                    'system_state': {
                        'core_heat': 0.0,
                        'last_processed_timestamp': datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    }
                }
        except Exception as e:
            raise LedgerLoadError(f"Corrupted or unreadable ledger file at {ledger_path}: {e}") from e
    return {
        'ledger': {},
        'system_state': {
            'core_heat': 0.0,
            'last_processed_timestamp': datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        }
    }


def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e


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

    ledger_data = load_ledger(ledger_path)
    ledger_entries = ledger_data.get('ledger', {})
    system_state = ledger_data.get('system_state', {})

    now_utc = datetime.now(timezone.utc)
    last_ts_str = system_state.get('last_processed_timestamp')
    if last_ts_str:
        try:
            if last_ts_str.endswith('Z'):
                last_ts = datetime.strptime(last_ts_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            else:
                last_ts = datetime.strptime(last_ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            elapsed_sec = max(0.0, (now_utc - last_ts).total_seconds())
        except Exception:
            elapsed_sec = 0.0
    else:
        elapsed_sec = 0.0

    current_heat = max(0.0, float(system_state.get('core_heat', 0.0)) - elapsed_sec * COOLING_RATE_PER_SEC)

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

        if idempotency_key in ledger_entries:
            term_outcome = ledger_entries[idempotency_key].get('terminal_outcome')
            if term_outcome in [DNAStatus.SUCCESS.value, DNAStatus.ERROR.value, DNAStatus.SKIPPED.value, DNAStatus.REFUSED.value, 'success', 'error', 'skipped', 'refused']:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
                log_structured(correlation_id=correlation_id, step="dedupe", outcome=DNAStatus.SKIPPED.value, idempotency_key=idempotency_key, outcome_detail="already processed")
                continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if current_heat + HEAT_PER_SEQUENCE > MAX_HEAT_THRESHOLD:
            print(f"[{MSG_REFUSAL_REASON}] Core heat ({current_heat:.2f}) + addition exceeds threshold ({MAX_HEAT_THRESHOLD:.2f}). {MSG_NEXT_ACTION_HINT}")
            log_structured(
                correlation_id=correlation_id,
                step="thermal_check",
                outcome=DNAStatus.REFUSED.value,
                idempotency_key=idempotency_key,
                outcome_detail=f"{MSG_REFUSAL_REASON}: {MSG_NEXT_ACTION_HINT}"
            )
            system_state['core_heat'] = current_heat
            system_state['last_processed_timestamp'] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            save_ledger(ledger_path, ledger_data)
            raise ThermalOverloadError(f"{MSG_REFUSAL_REASON}: Core heat limit exceeded. {MSG_NEXT_ACTION_HINT}")

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
        current_heat += HEAT_PER_SEQUENCE
        now_utc = datetime.now(timezone.utc)
        now_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str,
            'consequence': MSG_CONSEQUENCE_APPLIED
        }
        system_state['core_heat'] = current_heat
        system_state['last_processed_timestamp'] = now_str
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            step="parse",
            outcome=outcome,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
            outcome_detail=f"Parsed sequence. Consequence: {MSG_CONSEQUENCE_APPLIED}"
        )

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

        save_ledger(ledger_path, ledger_data)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger_entries)}")


main = run_batch

if __name__ == '__main__':
    main()
