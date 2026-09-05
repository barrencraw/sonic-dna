#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# Exception Taxonomy
class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing the ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when writing the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic write of output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal threshold is reached and system is locked out."""
    pass

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

def log_structured(event, **kwargs):
    """
    Emits structured telemetry JSON logs prefixed with 'JSON_LOG:'.
    """
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = {
        "timestamp": now_str,
        "correlation_id": kwargs.get("correlation_id", "none"),
        "actor_id": kwargs.get("actor_id", "batch_parser"),
        "chain_name": kwargs.get("chain_name", "dna_batch_parsing"),
        "step": kwargs.get("step", event),
        "outcome": kwargs.get("outcome", DNAStatus.SUCCESS.value),
        "latency_ms": kwargs.get("latency_ms", 0),
        "idempotency_key": kwargs.get("idempotency_key", "none"),
        "outcome_detail": kwargs.get("outcome_detail", "")
    }
    for k, v in kwargs.items():
        if k not in log_entry:
            log_entry[k] = v
    print(f"JSON_LOG:{json.dumps(log_entry)}")

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
    """
    Loads ledger file. Returns structured format:
    {'ledger': {...}, 'system_state': {'core_heat': float, 'last_processed_timestamp': str}}
    """
    default_structure = {
        'ledger': {},
        'system_state': {
            'core_heat': 0.0,
            'last_processed_timestamp': None
        }
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}") from e

        if isinstance(raw_data, dict):
            if 'ledger' in raw_data and isinstance(raw_data['ledger'], dict):
                system_state = raw_data.get('system_state', {})
                if not isinstance(system_state, dict):
                    system_state = {}
                default_structure['ledger'] = raw_data['ledger']
                default_structure['system_state']['core_heat'] = float(system_state.get('core_heat', 0.0))
                default_structure['system_state']['last_processed_timestamp'] = system_state.get('last_processed_timestamp', None)
                return default_structure
            else:
                # Legacy flat layout
                default_structure['ledger'] = raw_data
                return default_structure
        else:
            raise LedgerLoadError(f"Invalid ledger format at {ledger_path}")
    return default_structure

def save_ledger(ledger_path, ledger_data):
    """
    Saves structured ledger atomically to ledger_path.
    """
    parent_dir = os.path.dirname(ledger_path) or '.'
    ensure_folder(parent_dir)
    try:
        with tempfile.TemporaryDirectory(dir=parent_dir) as tmp_dir:
            tmp_file = os.path.join(tmp_dir, 'ledger.json')
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(ledger_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None, actor_id='batch_parser'):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    start_time = time.time()
    log_structured(
        "batch_start",
        correlation_id=correlation_id,
        actor_id=actor_id,
        step="batch_start",
        outcome=DNAStatus.SUCCESS.value
    )

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            "batch_end",
            correlation_id=correlation_id,
            actor_id=actor_id,
            step="batch_end",
            outcome=DNAStatus.SKIPPED.value,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        log_structured(
            "batch_end",
            correlation_id=correlation_id,
            actor_id=actor_id,
            step="batch_end",
            outcome=DNAStatus.SKIPPED.value,
            outcome_detail="No DNA sequences found in toSequence.txt"
        )
        return

    # Load ledger
    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data['ledger']
    system_state = ledger_data['system_state']

    current_heat = system_state.get('core_heat', 0.0)
    last_time_str = system_state.get('last_processed_timestamp')

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Apply cooling dissipation
    if last_time_str:
        try:
            last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = (now_dt - last_dt).total_seconds()
            if elapsed_sec > 0:
                dissipated = elapsed_sec * 0.5
                current_heat = max(0.0, current_heat - dissipated)
        except Exception:
            pass

    system_state['core_heat'] = current_heat

    # Load existing JSON output
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

    # Load existing CSV rows
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')
    csv_rows = []
    all_flattened_keys = set(['dna', 'dna_sequence'])
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as cf:
                reader = csv.DictReader(cf)
                if reader.fieldnames:
                    all_flattened_keys.update(reader.fieldnames)
                    csv_rows = list(reader)
        except Exception:
            pass

    new_processed_count = 0
    lockout_occurred = False

    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq

        if idempotency_key in ledger:
            existing_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS.value)
            log_structured(
                "idempotency_check",
                correlation_id=correlation_id,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome=DNAStatus.SKIPPED.value,
                outcome_detail=f"dedupe_hit=True terminal_outcome={existing_outcome}"
            )
            continue

        # Check thermal fatigue lockout
        if current_heat >= 10.0:
            lockout_occurred = True
            log_structured(
                "sequence_parse",
                correlation_id=correlation_id,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome=DNAStatus.REFUSED.value,
                reason="Thermal Lockout",
                hint="Wait for dissipation. The system is indifferent to your deadlines.",
                outcome_detail="Core heat exceeded threshold (10.0)"
            )
            ledger[idempotency_key] = {
                'terminal_outcome': DNAStatus.REFUSED.value,
                'timestamp': now_iso
            }
            new_processed_count += 1
            break

        # Process sequence
        seq_start_time = time.time()
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
            outcome_detail = "Successfully parsed"

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
            outcome_detail = f"RuleParseError: {str(e)}"

        seq_latency = int((time.time() - seq_start_time) * 1000)
        current_heat += 2.0
        system_state['core_heat'] = current_heat
        system_state['last_processed_timestamp'] = now_iso

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_iso
        }
        new_processed_count += 1

        log_structured(
            "sequence_parse",
            correlation_id=correlation_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            outcome=outcome,
            latency_ms=seq_latency,
            consequence="Heat Accumulation",
            core_heat=current_heat,
            outcome_detail=outcome_detail
        )

        if current_heat >= 10.0:
            lockout_occurred = True
            log_structured(
                "thermal_lockout_triggered",
                correlation_id=correlation_id,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome=DNAStatus.REFUSED.value,
                reason="Thermal Lockout",
                hint="Wait for dissipation. The system is indifferent to your deadlines.",
                outcome_detail="System reached thermal lockout threshold"
            )
            break

    if new_processed_count > 0:
        # Atomic write of output files
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

        # Save ledger
        save_ledger(ledger_path, ledger_data)

    total_latency = int((time.time() - start_time) * 1000)
    log_structured(
        "batch_end",
        correlation_id=correlation_id,
        actor_id=actor_id,
        step="batch_end",
        outcome=DNAStatus.REFUSED.value if lockout_occurred else DNAStatus.SUCCESS.value,
        latency_ms=total_latency,
        processed_count=new_processed_count
    )

    if lockout_occurred:
        raise ThermalOverloadError("Thermal Lockout: Heat Accumulation threshold reached. Wait for dissipation. The system is indifferent to your deadlines.")

main = run_batch

if __name__ == '__main__':
    run_batch()
