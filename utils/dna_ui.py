#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import uuid
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys
MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# Systemic Parameters
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
    """Raised when reading input file fails."""
    pass


class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass


class ThermalOverloadError(DNAProcessingError):
    """Raised when core heat exceeds safety lockout threshold."""
    pass


class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when reading ledger file fails or JSON is invalid."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving ledger file fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when atomic write of output files fails."""
    pass


def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail=None):
    payload = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'correlation_id': correlation_id or str(uuid.uuid4()),
        'actor_id': actor_id or 'batch_parser',
        'chain_name': chain_name or 'dna_batch_processing',
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail or {}
    }
    print(f"JSON_LOG:{json.dumps(payload)}")


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
                    raise LedgerLoadError(f"Invalid ledger content at {ledger_path}")
                if "ledger" in data and "system_state" in data:
                    return data["ledger"], data["system_state"]
                else:
                    # Legacy flat layout
                    return data, {"core_heat": 0.0, "last_processed_timestamp": None}
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}") from e
        except Exception as e:
            if isinstance(e, LedgerLoadError):
                raise
            raise LedgerLoadError(f"Error loading ledger at {ledger_path}: {e}") from e
    return {}, {"core_heat": 0.0, "last_processed_timestamp": None}


def save_ledger(ledger_path, ledger, system_state):
    data = {
        "ledger": ledger,
        "system_state": system_state
    }
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e


def run_batch(correlation_id=None, actor_id='batch_parser'):
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

    ledger, system_state = load_ledger(ledger_path)
    initial_ledger = dict(ledger)

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    current_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = (now_utc - last_time).total_seconds()
            if elapsed_seconds > 0:
                current_heat = max(0.0, current_heat - elapsed_seconds * COOLING_RATE_PER_SEC)
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
        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name='dna_batch_processing',
                step='deduplication_check',
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=int((time.time() - start_time) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail={'message': 'Skipped duplicate DNA sequence', 'previous_outcome': term_outcome}
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Thermal fatigue lockout check
        if current_heat + HEAT_PER_SEQUENCE > LOCKOUT_THRESHOLD:
            system_state['core_heat'] = current_heat
            system_state['last_processed_timestamp'] = now_str
            save_ledger(ledger_path, initial_ledger, system_state)

            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name='dna_batch_processing',
                step='thermal_check',
                outcome=DNAStatus.REFUSED.value,
                latency_ms=int((time.time() - start_time) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail={
                    'consequence': MSG_CONSEQUENCE_APPLIED,
                    'reason': MSG_REFUSAL_REASON,
                    'hint': MSG_NEXT_ACTION_HINT,
                    'current_heat': current_heat
                }
            )

            err_msg = (
                f"{MSG_REFUSAL_REASON}: {MSG_CONSEQUENCE_APPLIED} ({current_heat:.1f} heat units). "
                f"Processing '{dna_seq}' would exceed threshold ({LOCKOUT_THRESHOLD:.1f}). "
                f"{MSG_NEXT_ACTION_HINT}"
            )
            raise ThermalOverloadError(err_msg)

        current_heat += HEAT_PER_SEQUENCE

        seq_start = time.time()
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
            outcome_detail = {'rule': result['rule']}

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value
            outcome_detail = {'error': str(e)}

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        system_state['core_heat'] = current_heat
        system_state['last_processed_timestamp'] = now_str
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name='dna_batch_processing',
            step='parse_sequence',
            outcome=outcome,
            latency_ms=int((time.time() - seq_start) * 1000),
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
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

        save_ledger(ledger_path, ledger, system_state)
    else:
        # Update system state for cooling if heat decayed without new processing
        save_ledger(ledger_path, ledger, system_state)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")


main = run_batch

if __name__ == '__main__':
    main()
