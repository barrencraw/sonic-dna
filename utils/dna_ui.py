#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# Standardized UI Message Keys
CONSEQUENCE_KEY = "Heat Accumulation"
REFUSAL_REASON_KEY = "Thermal Lockout"
NEXT_ACTION_HINT_KEY = "Wait for dissipation. The system is indifferent to your deadlines."

# Thermal Fatigue Constants
HEAT_PER_SEQUENCE = 2.0
MAX_CORE_HEAT = 10.0
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
    """Raised when reading the input file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading the processed ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic writing of output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system core heat reaches safety lockout threshold."""
    pass


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
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    if 'ledger' in loaded and 'system_state' in loaded:
                        return loaded
                    else:
                        # Convert legacy flat ledger layout to structured layout
                        return {
                            'ledger': loaded,
                            'system_state': {
                                'core_heat': 0.0,
                                'last_processed_timestamp': None
                            }
                        }
                return {
                    'ledger': {},
                    'system_state': {
                        'core_heat': 0.0,
                        'last_processed_timestamp': None
                    }
                }
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
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
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e


def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    actor_id = "batch_parser"
    chain_name = "dna_batch_parsing"

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
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

    ledger_data = load_ledger(ledger_path)
    ledger_entries = ledger_data.get('ledger', {})
    system_state = ledger_data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})

    # Thermal dissipation calculation
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    last_time_str = system_state.get('last_processed_timestamp')

    current_heat = float(system_state.get('core_heat', 0.0))
    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ')
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = (now_utc - last_time).total_seconds()
            if elapsed_seconds > 0:
                dissipated_heat = elapsed_seconds * COOLING_RATE_PER_SEC
                current_heat = max(0.0, current_heat - dissipated_heat)
        except Exception:
            pass

    # Filter out deduplicated sequences (both in ledger and within batch)
    new_sequences = []
    seen_in_batch = set()
    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger_entries or idempotency_key in seen_in_batch:
            outcome_val = ledger_entries.get(idempotency_key, {}).get('terminal_outcome', DNAStatus.SKIPPED.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={outcome_val}")
        else:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
            new_sequences.append(dna_seq)
            seen_in_batch.add(idempotency_key)

    if not new_sequences:
        print("[Idempotency] All DNA sequences deduplicated. No action required.")
        return

    # Check thermal lockout before processing new sequences
    if current_heat >= MAX_CORE_HEAT:
        log_structured(
            timestamp=now_str,
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="thermal_check",
            outcome=DNAStatus.REFUSED.value,
            latency_ms=0,
            idempotency_key="batch_start",
            outcome_detail=f"{REFUSAL_REASON_KEY}: {NEXT_ACTION_HINT_KEY}"
        )
        raise ThermalOverloadError(f"{REFUSAL_REASON_KEY}: {NEXT_ACTION_HINT_KEY}")

    # Load existing JSON and CSV outputs
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
    for dna_seq in new_sequences:
        idempotency_key = dna_seq

        if current_heat >= MAX_CORE_HEAT:
            log_structured(
                timestamp=now_str,
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step="parse_sequence",
                outcome=DNAStatus.REFUSED.value,
                latency_ms=0,
                idempotency_key=idempotency_key,
                outcome_detail=f"{REFUSAL_REASON_KEY}: {NEXT_ACTION_HINT_KEY}"
            )
            raise ThermalOverloadError(f"{REFUSAL_REASON_KEY}: {NEXT_ACTION_HINT_KEY}")

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
            detail = "Parsed successfully"

        except RuleParseError as e:
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
            outcome = DNAStatus.ERROR.value
            detail = str(e)

        latency_ms = int((time.time() - start_time) * 1000)
        current_heat += HEAT_PER_SEQUENCE

        ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        new_processed_count += 1

        log_structured(
            timestamp=now_str,
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="parse_sequence",
            outcome=outcome,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
            outcome_detail=f"{CONSEQUENCE_KEY}: +{HEAT_PER_SEQUENCE} heat (core={current_heat:.1f}). {detail}"
        )

    # Atomic write pattern for JSON and CSV output files if new items were processed
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

        # Save updated ledger structure
        system_state['core_heat'] = current_heat
        system_state['last_processed_timestamp'] = now_str
        updated_ledger_data = {
            'ledger': ledger_entries,
            'system_state': system_state
        }
        save_ledger(ledger_path, updated_ledger_data)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger_entries)}. Core heat: {current_heat:.1f}")

main = run_batch

if __name__ == '__main__':
    run_batch()
