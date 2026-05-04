#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError, ParsedDNA

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"

def log_observability(event: str, correlation_id: str, data: dict = None, outcome: Outcome = None, actor_id: str = "system"):
    """
    Standardized pipe-delimited telemetry.
    Grep Recipe: grep "| TELEMETRY |" <log_file> | jq '.data'
    """
    payload = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id,
        "event": event,
        "actor_id": actor_id,
    }
    if data:
        payload["data"] = data
    if outcome:
        payload["outcome"] = outcome.value

    print(f"| TELEMETRY | {json.dumps(payload)}")

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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def main(data_dir=None):
    correlation_id = str(uuid.uuid4())
    log_observability("[Batch Start]", correlation_id, outcome=Outcome.START)

    # Determine file paths
    project_root = os.getcwd()
    base_dir = data_dir if data_dir else project_root
    raw_folder = os.path.join(base_dir, 'data', 'raw')
    output_folder = os.path.join(base_dir, 'data', 'output')
    ledger_path = os.path.join(base_dir, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability("Input file not found", correlation_id, {"path": input_file}, outcome=Outcome.ERROR)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability("Rule load failure", correlation_id, {"error": str(e)}, outcome=Outcome.ERROR)
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("Input read failure", correlation_id, {"error": str(e)}, outcome=Outcome.ERROR)
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability("No DNA strings found", correlation_id, outcome=Outcome.END)
        return

    ledger = load_ledger(ledger_path)

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
    new_ledger_entries = {}

    for dna_str in dna_list:
        idempotency_key = dna_str

        # Check persistent ledger OR in-batch duplicates
        if idempotency_key in ledger or idempotency_key in new_ledger_entries:
            outcome_val = ledger.get(idempotency_key, {}).get('terminal_outcome') or new_ledger_entries.get(idempotency_key, {}).get('terminal_outcome')
            log_observability("[Idempotency]", correlation_id, {"key": idempotency_key, "dedupe_hit": True, "terminal_outcome": outcome_val})
            continue

        log_observability("[Idempotency]", correlation_id, {"key": idempotency_key, "dedupe_hit": False, "terminal_outcome": "processing"})

        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'rule': result.rule,
                'parsed': result.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result.rule, result.values)
            flat['dna'] = dna_str
            flat['rule'] = result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS

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
            outcome = Outcome.ERROR

        new_ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_observability("[Idempotency]", correlation_id, {"key": idempotency_key, "dedupe_hit": False, "terminal_outcome": outcome.value})
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC COMMIT PATTERN:
        # 1. Update ledger with new entries
        ledger.update(new_ledger_entries)

        # 2. Write to a temporary directory in the same filesystem as the output folder
        with tempfile.TemporaryDirectory(dir=os.path.dirname(ledger_path) if os.path.dirname(ledger_path) else ".") as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

            try:
                # Write JSON output to temp
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # Write CSV output to temp
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # Write Ledger to temp
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # Atomic renames
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                log_observability("Persistence failure", correlation_id, {"error": str(e)}, outcome=Outcome.ERROR)
                raise PersistenceError("Failed to commit outputs and ledger atomically") from e

    log_observability("[Terminal Outcome]", correlation_id, {"processed_new": new_processed_count, "total_ledger": len(ledger)}, outcome=Outcome.SUCCESS)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
