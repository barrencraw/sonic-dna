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


class DNAStatus(str, Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'


class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass


class InputReadError(DNAProcessingError):
    """Raised when reading input DNA sequence file fails."""
    pass


class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass


class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when reading or parsing the ledger file fails."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when writing the ledger file fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass


class ThermalOverloadError(DNAProcessingError):
    """Raised when core heat exceeds safety lockout threshold."""
    pass


def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail=None):
    log_payload = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail or {}
    }
    print(f"JSON_LOG: {json.dumps(log_payload)}")


def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequence_list = []
    if not os.path.exists(input_path):
        return dna_sequence_list
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
                if isinstance(data, dict):
                    if 'ledger' in data and isinstance(data['ledger'], dict):
                        return data
                    return {
                        'ledger': data,
                        'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}
                    }
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger file: {ledger_path}") from e
    return {
        'ledger': {},
        'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}
    }


def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger: {e}") from e


def run_batch(correlation_id=None, actor_id='batch_parser'):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    chain_name = 'dna_batch_parser'
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    rules_folder = os.path.join(project_root, 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {rules_folder}") from e

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    dna_sequence_list = read_input_file(input_file)

    structured_ledger = load_ledger(ledger_path)
    ledger = structured_ledger.get('ledger', {})
    system_state = structured_ledger.get('system_state', {})

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')
    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (now_utc - last_time).total_seconds())
            core_heat = max(0.0, core_heat - 0.5 * elapsed_seconds)
        except Exception:
            pass

    if not dna_sequence_list:
        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = now_iso
        structured_ledger['ledger'] = ledger
        structured_ledger['system_state'] = system_state
        save_ledger(ledger_path, structured_ledger)
        return

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                content = json.load(jf)
                if isinstance(content, list):
                    parsed_json = content
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
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step='idempotency_check',
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=0.0,
                idempotency_key=idempotency_key,
                outcome_detail={'dedupe_hit': True, 'terminal_outcome': existing_outcome}
            )
            continue

        if core_heat >= 10.0:
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step='thermal_lockout',
                outcome=DNAStatus.REFUSED.value,
                latency_ms=0.0,
                idempotency_key=idempotency_key,
                outcome_detail={
                    'reason': 'Thermal Lockout',
                    'hint': 'Wait for dissipation. The system is indifferent to your deadlines.',
                    'core_heat': core_heat
                }
            )
            ledger[idempotency_key] = {
                'terminal_outcome': DNAStatus.REFUSED.value,
                'reason': 'Thermal Lockout',
                'timestamp': now_iso
            }
            system_state['core_heat'] = core_heat
            system_state['last_processed_timestamp'] = now_iso
            structured_ledger['ledger'] = ledger
            structured_ledger['system_state'] = system_state
            save_ledger(ledger_path, structured_ledger)

            raise ThermalOverloadError(
                "Thermal Lockout: Core heat limit exceeded. Wait for dissipation. The system is indifferent to your deadlines."
            )

        t0 = time.time()
        try:
            result = calculator.parse(dna_seq)
            latency_ms = (time.time() - t0) * 1000
            outcome = DNAStatus.SUCCESS.value
            core_heat += 2.0

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

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': now_iso
            }

            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step='parse_sequence',
                outcome=outcome,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail={'rule': result['rule'], 'Heat Accumulation': 2.0, 'core_heat': core_heat}
            )
            new_processed_count += 1

        except RuleParseError as e:
            latency_ms = (time.time() - t0) * 1000
            outcome = DNAStatus.ERROR.value

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

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'error': str(e),
                'timestamp': now_iso
            }

            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step='parse_sequence',
                outcome=outcome,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail={'error': str(e)}
            )
            new_processed_count += 1

    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = now_iso
    structured_ledger['ledger'] = ledger
    structured_ledger['system_state'] = system_state
    save_ledger(ledger_path, structured_ledger)

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


main = run_batch


if __name__ == '__main__':
    main()
