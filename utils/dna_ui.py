#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class BatchResult:
    def __init__(self, status, processed_count, total_ledger_items):
        self.status = status
        self.processed_count = processed_count
        self.total_ledger_items = total_ledger_items

    def __repr__(self):
        return f"BatchResult(status={self.status}, processed_count={self.processed_count}, total_ledger_items={self.total_ledger_items})"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic writes fail."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when the mainframe core heat reaches or exceeds the safety lockout threshold."""
    def __init__(self, message="Thermal Lockout. Heat Accumulation. Wait for dissipation. The system is indifferent to your deadlines."):
        super().__init__(message)

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
                return json.load(f)
        except Exception:
            raise LedgerLoadError("Failed to load corrupted ledger file")
    return {}

def save_ledger(ledger_path, ledger):
    folder = os.path.dirname(ledger_path)
    ensure_folder(folder)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=folder, suffix='.tmp')
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise LedgerSaveError("Failed to save ledger atomically") from e

def log_structured(step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None, correlation_id=None):
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    log_data = {
        'timestamp': now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'correlation_id': correlation_id or 'default_correlation_id',
        'actor_id': 'system_batch_processor',
        'chain_name': 'dna_batch_parser_chain',
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None):
    start_time = time.time()
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return BatchResult("NO_NEW_ITEMS", 0, 0)

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return BatchResult("NO_NEW_ITEMS", 0, 0)

    ledger = load_ledger(ledger_path)

    # Load system state for Thermal Fatigue
    system_state = ledger.get('__system_state__', {})
    core_heat = system_state.get('core_heat', 0.0)
    last_processed_timestamp = system_state.get('last_processed_timestamp', None)

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Calculate heat dissipation (0.5 units/second)
    if last_processed_timestamp:
        try:
            last_time = datetime.datetime.strptime(last_processed_timestamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = (now_utc - last_time).total_seconds()
            dissipated_heat = elapsed_seconds * 0.5
            core_heat = max(0.0, core_heat - dissipated_heat)
        except Exception:
            pass

    print(f"[Thermal State] Current core heat calculated: {core_heat:.2f}/10.0")

    # 1) Load existing JSON output
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

    # 2) Load existing CSV rows
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
    error_occurred = False

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                log_structured('deduplication', 'skipped', idempotency_key=idempotency_key, correlation_id=correlation_id)
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            # Thermal Fatigue Check
            if core_heat >= 10.0:
                # Lockout state triggered!
                outcome = DNAStatus.REFUSED.value
                ledger[idempotency_key] = {
                    'terminal_outcome': outcome,
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
                }
                new_processed_count += 1
                error_occurred = True

                # Update system state before saving
                ledger['__system_state__'] = {
                    'core_heat': core_heat,
                    'last_processed_timestamp': now_str
                }

                log_structured('parsing', 'refused', idempotency_key=idempotency_key, outcome_detail='Thermal Lockout', correlation_id=correlation_id)

                # Save ledger and outputs atomically up to this refusal
                try:
                    save_ledger(ledger_path, ledger)
                except Exception:
                    pass

                raise ThermalOverloadError(
                    "Thermal Lockout. Heat Accumulation. "
                    "Wait for dissipation. The system is indifferent to your deadlines."
                )

            try:
                result = calculator.parse(dna_str)
                entry = {
                    'dna': dna_str,
                    'dna_sequence': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_str
                flat['dna_sequence'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.SUCCESS.value

                # Successful parse adds 2.0 heat units
                core_heat += 2.0
                print(f"[Thermal State] Successfully parsed sequence '{dna_str}'. Heat +2.0 -> {core_heat:.2f}/10.0")
                log_structured('parsing', 'success', idempotency_key=idempotency_key, correlation_id=correlation_id)

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_str,
                    'dna_sequence': dna_str,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR.value
                log_structured('parsing', 'error', idempotency_key=idempotency_key, outcome_detail=str(e), correlation_id=correlation_id)

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
            new_processed_count += 1

            # Update now_str
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    finally:
        if new_processed_count > 0:
            # Update system state in ledger
            ledger['__system_state__'] = {
                'core_heat': core_heat,
                'last_processed_timestamp': now_str
            }

            # 1. Atomic write ledger
            try:
                save_ledger(ledger_path, ledger)
            except Exception as e:
                # Structured-logged with step 'cleanup_failure'
                log_structured('cleanup_failure', 'error', outcome_detail=str(e), correlation_id=correlation_id)
                if not error_occurred:
                    raise

            # 2. Atomic write outputs
            try:
                with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                    tmp_json = os.path.join(tmp_dir, 'output.json')
                    tmp_csv = os.path.join(tmp_dir, 'output.csv')

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
                log_structured('cleanup_failure', 'error', outcome_detail=str(e), correlation_id=correlation_id)
                if not error_occurred:
                    raise AtomicWriteError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA sequences.")
    status = "SUCCESS" if new_processed_count > 0 else "NO_NEW_ITEMS"
    total_items = len(ledger) - 1 if '__system_state__' in ledger else len(ledger)
    return BatchResult(status, new_processed_count, total_items)

# Alias main to run_batch for backwards compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
