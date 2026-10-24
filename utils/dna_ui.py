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

# System Constants for Thermal Fatigue
HEAT_PER_SEQUENCE = 2.0
MAX_HEAT = 10.0
COOLING_RATE = 0.5  # Heat units per second

# UI Message Keys
MSG_CONSEQUENCE_APPLIED = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when core heat meets or exceeds maximum threshold."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading the processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass

def log_structured(correlation_id=None, actor_id="batch_parser", chain_name="dna_batch_parser", step="process_batch", outcome="success", latency_ms=0, idempotency_key=None, outcome_detail=None):
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "",
        "outcome_detail": outcome_detail or ""
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
                    raise LedgerLoadError(f"Invalid ledger format in {ledger_path}")
                if 'ledger' in data and isinstance(data['ledger'], dict):
                    return data['ledger'], data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': ''})
                else:
                    return data, {'core_heat': 0.0, 'last_processed_timestamp': ''}
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Corrupted ledger file: {ledger_path}") from e
        except Exception as e:
            if isinstance(e, DNAProcessingError):
                raise
            raise LedgerLoadError(f"Failed to load ledger: {e}") from e
    return {}, {'core_heat': 0.0, 'last_processed_timestamp': ''}

def save_ledger(ledger_path, ledger, system_state):
    try:
        payload = {
            'ledger': ledger,
            'system_state': system_state
        }
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger: {e}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
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
        log_structured(correlation_id, actor_id, step="check_input", outcome=DNAStatus.ERROR, outcome_detail="Input file not found")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, actor_id, step="load_rules", outcome=DNAStatus.ERROR, outcome_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        log_structured(correlation_id, actor_id, step="read_input", outcome=DNAStatus.SKIPPED, outcome_detail="Empty input file")
        return

    ledger, system_state = load_ledger(ledger_path)
    initial_ledger = dict(ledger)

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Calculate thermal dissipation
    last_time_str = system_state.get('last_processed_timestamp', '')
    core_heat = float(system_state.get('core_heat', 0.0))

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ')
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (now_utc - last_time).total_seconds())
            core_heat = max(0.0, core_heat - elapsed_seconds * COOLING_RATE)
        except Exception:
            pass

    # Load existing JSON output
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                content = json.load(jf)
                if isinstance(content, list):
                    parsed_json = content
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

    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence

        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(correlation_id, actor_id, step="parse_sequence", outcome=DNAStatus.SKIPPED, idempotency_key=idempotency_key)
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Check thermal overload condition
        if core_heat + HEAT_PER_SEQUENCE > MAX_HEAT:
            system_state['core_heat'] = core_heat
            system_state['last_processed_timestamp'] = now_str
            save_ledger(ledger_path, initial_ledger, system_state)

            log_structured(correlation_id, actor_id, step="thermal_check", outcome=DNAStatus.REFUSED, idempotency_key=idempotency_key, outcome_detail=f"{MSG_REFUSAL_REASON}: {MSG_CONSEQUENCE_APPLIED}")

            err_msg = f"[{MSG_REFUSAL_REASON}] {MSG_CONSEQUENCE_APPLIED}: Core heat {core_heat:.1f} + {HEAT_PER_SEQUENCE:.1f} exceeds threshold {MAX_HEAT:.1f}. {MSG_NEXT_ACTION_HINT}"
            raise ThermalOverloadError(err_msg)

        core_heat += HEAT_PER_SEQUENCE

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

            outcome = DNAStatus.SUCCESS
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': now_str,
                'dna_sequence': dna_sequence
            }
            new_processed_count += 1
            log_structured(correlation_id, actor_id, step="parse_sequence", outcome=outcome, idempotency_key=idempotency_key)

        except RuleParseError as e:
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            }
            parsed_json.append(entry)

            flat = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            }
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.ERROR
            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': now_str,
                'dna_sequence': dna_sequence
            }
            new_processed_count += 1
            log_structured(correlation_id, actor_id, step="parse_sequence", outcome=outcome, idempotency_key=idempotency_key, outcome_detail=str(e))

    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = now_str

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

    latency_ms = int((time.time() - start_time) * 1000)
    log_structured(correlation_id, actor_id, step="batch_complete", outcome=DNAStatus.SUCCESS, latency_ms=latency_ms, outcome_detail=f"Processed {new_processed_count} new DNA sequences")

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Core heat: {core_heat:.1f}")

main = run_batch

if __name__ == '__main__':
    main()
