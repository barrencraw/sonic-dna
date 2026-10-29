#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
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
    """Raised when reading input DNA sequence file fails."""
    pass


class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass


class PersistenceError(DNAProcessingError):
    """Base class for persistence related errors."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing the ledger fails."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when writing or replacing output files fails."""
    pass


class ThermalOverloadError(DNAProcessingError):
    """Raised when system thermal lockout threshold is exceeded."""
    pass


def log_structured(
    event: str,
    correlation_id: str = None,
    actor_id: str = "batch_parser",
    chain_name: str = "dna_batch_parser",
    step: str = "process_sequence",
    outcome: str = "success",
    latency_ms: float = 0.0,
    idempotency_key: str = None,
    outcome_detail: str = None,
    **extra
):
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = {
        "timestamp": now_utc,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or event,
    }
    if extra:
        log_entry.update(extra)
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
    except (IOError, OSError) as e:
        raise InputReadError(f"Failed to read input file {input_path}: {e}") from e
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
    """
    Loads ledger and system state. Raises LedgerLoadError on corrupted files.
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if 'ledger' in data and 'system_state' in data:
                        return data
                    else:
                        # Legacy flat ledger dictionary format
                        return {
                            'ledger': data,
                            'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}
                        }
                return {
                    'ledger': {},
                    'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}
                }
        except Exception as e:
            raise LedgerLoadError(f"Corrupted or invalid JSON ledger at {ledger_path}: {e}") from e
    return {
        'ledger': {},
        'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}
    }


def save_ledger(ledger_path, ledger_data):
    """
    Saves structured ledger data to ledger_path.
    """
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e


def run_batch(correlation_id=None, actor_id="batch_parser"):
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')

    # Paths defined unconditionally at top level
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            event="Input file not found",
            correlation_id=correlation_id,
            actor_id=actor_id,
            step="input_check",
            outcome=DNAStatus.SKIPPED.value,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Load ledger and system state
    structured_ledger = load_ledger(ledger_path)
    ledger_entries = structured_ledger.get('ledger', {})
    system_state = structured_ledger.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})

    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    if last_time_str:
        try:
            if last_time_str.endswith('Z'):
                last_time_str_clean = last_time_str[:-1]
            else:
                last_time_str_clean = last_time_str
            last_dt = datetime.datetime.strptime(last_time_str_clean, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=datetime.timezone.utc)
            elapsed = (now_dt - last_dt).total_seconds()
            if elapsed > 0:
                # Cool down rate: 0.5 heat units / second
                core_heat = max(0.0, core_heat - elapsed * 0.5)
        except Exception:
            pass

    # Initial lockout check
    if core_heat >= 10.0:
        log_structured(
            event="Thermal Lockout",
            correlation_id=correlation_id,
            actor_id=actor_id,
            step="thermal_check",
            outcome=DNAStatus.REFUSED.value,
            outcome_detail="Thermal Lockout",
            core_heat=core_heat
        )
        raise ThermalOverloadError(
            "Thermal Lockout: Heat Accumulation threshold exceeded. "
            "Wait for dissipation. The system is indifferent to your deadlines."
        )

    # Load Calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        log_structured(
            event="No DNA sequences found",
            correlation_id=correlation_id,
            actor_id=actor_id,
            step="read_input",
            outcome=DNAStatus.SKIPPED.value,
            outcome_detail="toSequence.txt is empty"
        )
        return

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

    def commit_outputs_and_ledger():
        now_utc_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = now_utc_str
        save_ledger(ledger_path, {'ledger': ledger_entries, 'system_state': system_state})

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

    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger_entries:
            prev_outcome = ledger_entries[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS.value)
            log_structured(
                event="Deduplication hit",
                correlation_id=correlation_id,
                actor_id=actor_id,
                step="idempotency_check",
                outcome=DNAStatus.SKIPPED.value,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated (previous outcome: {prev_outcome})"
            )
            continue

        if core_heat >= 10.0:
            if new_processed_count > 0:
                commit_outputs_and_ledger()
            log_structured(
                event="Thermal Lockout",
                correlation_id=correlation_id,
                actor_id=actor_id,
                step="process_sequence",
                outcome=DNAStatus.REFUSED.value,
                idempotency_key=idempotency_key,
                outcome_detail="Thermal Lockout",
                core_heat=core_heat
            )
            raise ThermalOverloadError(
                "Thermal Lockout: Heat Accumulation threshold exceeded. "
                "Wait for dissipation. The system is indifferent to your deadlines."
            )

        t0 = time.time()
        try:
            result = calculator.parse(dna_sequence)
            core_heat += 2.0
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
            core_heat += 2.0
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

        latency_ms = (time.time() - t0) * 1000.0
        now_ts = time.strftime('%Y-%m-%d %H:%M:%S')

        ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_ts
        }
        new_processed_count += 1

        log_structured(
            event=f"Processed DNA sequence ({outcome})",
            correlation_id=correlation_id,
            actor_id=actor_id,
            step="process_sequence",
            outcome=outcome,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
            outcome_detail=outcome
        )

    if new_processed_count > 0:
        commit_outputs_and_ledger()

    now_utc_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = now_utc_str
    save_ledger(ledger_path, {'ledger': ledger_entries, 'system_state': system_state})


main = run_batch


if __name__ == '__main__':
    run_batch()
