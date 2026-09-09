#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from enum import Enum

from utils.dna_calculator import DNACalculator, RuleParseError

# --- Constants & Message Keys ---
CONSEQUENCE_KEY = "Heat Accumulation"
REFUSAL_REASON_KEY = "Thermal Lockout"
NEXT_ACTION_HINT_KEY = "Wait for dissipation. The system is indifferent to your deadlines."

HEAT_PER_SEQUENCE = 2.0
MAX_HEAT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5
TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

# --- Status Enum ---
class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# --- Exception Taxonomy ---
class DNAProcessingError(Exception):
    """Base exception for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input DNA sequence file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when reading or parsing the processed ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when an atomic file replacement fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal capacity exceeds safety lockout threshold."""
    pass


def log_structured(timestamp, correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    payload = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name or "dna_batch_parsing",
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
    dna_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file {input_path}: {e}") from e
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
                return json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger at {ledger_path}: {e}") from e
    return {}


def save_ledger(ledger_path, data):
    try:
        dir_name = os.path.dirname(ledger_path)
        ensure_folder(dir_name)
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
            tmp_name = f.name
        os.replace(tmp_name, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e


def run_batch(correlation_id=None, actor_id='batch_parser'):
    start_time = time.time()
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

    raw_ledger_data = load_ledger(ledger_path)

    # Distinguish between structured ledger and legacy flat ledger
    if isinstance(raw_ledger_data, dict) and 'ledger' in raw_ledger_data:
        ledger = raw_ledger_data.get('ledger', {})
        system_state = raw_ledger_data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})
    elif isinstance(raw_ledger_data, dict):
        ledger = raw_ledger_data
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}
    else:
        ledger = {}
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}

    # Calculate thermal dissipation since last processed timestamp
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_utc.strftime(TIMESTAMP_FORMAT)

    current_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, TIMESTAMP_FORMAT)
            if last_time.tzinfo is None and now_utc.tzinfo is not None:
                last_time = last_time.replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (now_utc - last_time).total_seconds())
            dissipated_heat = elapsed_seconds * COOLING_RATE_PER_SEC
            current_heat = max(0.0, current_heat - dissipated_heat)
        except Exception:
            pass

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
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(
                timestamp=now_str,
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parsing",
                step="deduplication_check",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=int((time.time() - start_time) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated entry already exists with outcome {term_outcome}"
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Thermal fatigue threshold check before processing
        if current_heat + HEAT_PER_SEQUENCE > MAX_HEAT_THRESHOLD:
            msg = f"{REFUSAL_REASON_KEY}: Core heat {current_heat:.1f} + {HEAT_PER_SEQUENCE:.1f} exceeds threshold {MAX_HEAT_THRESHOLD:.1f}. {NEXT_ACTION_HINT_KEY}"
            log_structured(
                timestamp=now_str,
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parsing",
                step="thermal_check",
                outcome=DNAStatus.REFUSED.value,
                latency_ms=int((time.time() - start_time) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail=msg
            )
            raise ThermalOverloadError(msg)

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
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        current_heat += HEAT_PER_SEQUENCE
        system_state['core_heat'] = current_heat
        system_state['last_processed_timestamp'] = now_str

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str,
            'dna': dna_sequence,
            'dna_sequence': dna_sequence
        }
        print(f"[{CONSEQUENCE_KEY}] key={idempotency_key} current_heat={current_heat:.1f} terminal_outcome={outcome}")

        log_structured(
            timestamp=now_str,
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parsing",
            step="sequence_parsed",
            outcome=outcome,
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=idempotency_key,
            outcome_detail=f"{CONSEQUENCE_KEY}: sequence processed, core heat now {current_heat:.1f}"
        )

        new_processed_count += 1

    # Atomic write of output JSON & CSV only if new items were processed
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

        save_ledger(ledger_path, {'ledger': ledger, 'system_state': system_state})

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Core heat: {current_heat:.1f}. Total in ledger: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    main()
