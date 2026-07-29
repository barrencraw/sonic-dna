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

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
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

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when the system enters Thermal Lockout due to excess heat."""
    def __init__(self, message="Thermal Lockout", consequence="Heat Accumulation", hint="Wait for dissipation. The system is indifferent to your deadlines."):
        super().__init__(f"{message} - {consequence} - {hint}")
        self.message = message
        self.consequence = consequence
        self.hint = hint

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    ledger_dir = os.path.dirname(ledger_path)
    tmp_file = None
    try:
        ensure_folder(ledger_dir)
        fd, tmp_path = tempfile.mkstemp(dir=ledger_dir, prefix='.ledger_tmp_', suffix='.json')
        tmp_file = tmp_path
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        raise LedgerSaveError("Failed to save ledger atomically") from e

def run_batch(correlation_id=None):
    # Determine file paths
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

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    ledger = load_ledger(ledger_path)

    # 1) Thermal Fatigue Dissipation and Init
    current_time = datetime.datetime.now(datetime.timezone.utc)
    current_time_str = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    last_heat = float(ledger.get('system_heat', 0.0))
    last_time_str = ledger.get('last_processed_time')

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = (current_time - last_time).total_seconds()
            if elapsed_seconds < 0:
                elapsed_seconds = 0
        except Exception:
            elapsed_seconds = 0
    else:
        elapsed_seconds = 0

    cooling_rate = 0.5  # heat units per second
    dissipation = elapsed_seconds * cooling_rate
    current_heat = max(0.0, last_heat - dissipation)

    # Standardized constants for Thermal Fatigue
    LOCKOUT_THRESHOLD = 10.0
    HEAT_PER_SEQUENCE = 2.0

    # 2) Load existing JSON output
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

    # 3) Load existing CSV rows
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
    overloaded_exception = None

    if dna_list:
        try:
            for dna_str in dna_list:
                idempotency_key = dna_str
                # Skip if already exists in ledger with terminal success or error outcome
                if idempotency_key in ledger:
                    term_out = ledger[idempotency_key].get('terminal_outcome')
                    if term_out in [DNAStatus.SUCCESS.value, DNAStatus.ERROR.value]:
                        print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_out}")
                        continue

                # Lockout check: if we are over the threshold, we refuse the remaining strings
                if current_heat >= LOCKOUT_THRESHOLD:
                    print(f"[Thermal Lockout] Heat is {current_heat:.2f} >= {LOCKOUT_THRESHOLD:.2f}. Refusing {idempotency_key}.")
                    ledger[idempotency_key] = {
                        'terminal_outcome': DNAStatus.REFUSED.value,
                        'timestamp': current_time_str
                    }
                    print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={DNAStatus.REFUSED.value}")
                    new_processed_count += 1
                    raise ThermalOverloadError()

                print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

                try:
                    result = calculator.parse(dna_str)
                    entry = {
                        'dna': dna_str,
                        'rule': result['rule'],
                        'parsed': result['values']
                    }
                    parsed_json.append(entry)

                    # Flatten for CSV
                    flat = flatten_parsed(result['rule'], result['values'])
                    flat['dna'] = dna_str
                    flat['rule'] = result['rule']
                    csv_rows.append(flat)
                    all_flattened_keys.update(flat.keys())
                    outcome = DNAStatus.SUCCESS.value

                except RuleParseError as e:
                    # On parse error, record as error entry
                    parsed_json.append({
                        'dna': dna_str,
                        'error': str(e)
                    })
                    # Also put a row in CSV listing error
                    flat = {'dna': dna_str, 'error': str(e)}
                    csv_rows.append(flat)
                    all_flattened_keys.update(flat.keys())
                    outcome = DNAStatus.ERROR.value

                # Ledger update inside the loop
                ledger[idempotency_key] = {
                    'terminal_outcome': outcome,
                    'timestamp': current_time_str
                }
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
                new_processed_count += 1

                # Accumulate heat per sequence processed
                current_heat += HEAT_PER_SEQUENCE

        except ThermalOverloadError as toe:
            overloaded_exception = toe

    # Update global heat state in the ledger
    ledger['system_heat'] = current_heat
    ledger['last_processed_time'] = current_time_str

    # Write outputs atomically and save ledger if we processed any new items
    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
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
                raise PersistenceError("Failed to write output files atomically") from e

    # Save ledger
    save_ledger(ledger_path, ledger)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}. System heat: {current_heat:.2f}")

    if overloaded_exception:
        raise overloaded_exception

main = run_batch
