#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError, ParsedDNA

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if not os.path.isfile(input_path):
        return dna_list
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

def flatten_parsed(parsed_dna: ParsedDNA, parent_key=''):
    """
    Given ParsedDNA, flatten into { 'rule.sub1.sub2': value, ... }.
    Useful for CSV.
    """
    items = {}
    def _recurse(values, p_key):
        for k, v in values.items():
            new_key = f"{p_key}.{k}" if p_key else f"{parsed_dna.rule}.{k}"
            if isinstance(v, dict):
                _recurse(v, new_key)
            else:
                items[new_key] = v

    _recurse(parsed_dna.values, '')
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

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"

def log_observability(correlation_id, step, outcome: Outcome, chain_name="dna_batch_chain", latency_ms=None, actor_id="system", data=None):
    """
    Standardized structured logging for SonicDNA.
    Grep Recipe: grep "| TELEMETRY |" <log_file> | jq '.data'
    """
    payload = {
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.name,
        "latency_ms": latency_ms,
        "actor_id": actor_id,
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "data": data or {}
    }
    print(f"| TELEMETRY | {json.dumps(payload)}")

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def main(data_dir=None):
    correlation_id = str(uuid.uuid4())
    log_observability(correlation_id, "Batch Start", Outcome.START)
    start_time = time.time()

    # Determine file paths
    project_root = os.getcwd()
    if data_dir is None:
        data_dir = os.path.join(project_root, 'data')

    raw_folder = os.path.join(data_dir, 'raw')
    output_folder = os.path.join(data_dir, 'output')
    ledger_path = os.path.join(data_dir, 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, "Rule Load", Outcome.ERROR, data={"error": str(e)})
        raise RuleLoadError(f"Could not load rules") from e

    # Read DNA strings
    dna_list = read_input_file(input_file)
    if not dna_list:
        latency = int((time.time() - start_time) * 1000)
        log_observability(correlation_id, "Batch End", Outcome.END, latency_ms=latency, data={"processed": 0})
        return

    ledger = load_ledger(ledger_path)

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
    new_ledger_entries = {}

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger or idempotency_key in new_ledger_entries:
            outcome_val = ledger.get(idempotency_key, {}).get('terminal_outcome') or \
                          new_ledger_entries.get(idempotency_key, {}).get('terminal_outcome')
            log_observability(correlation_id, "Idempotency", Outcome.SKIPPED, data={"key": idempotency_key, "prev_outcome": outcome_val})
            continue

        try:
            parsed_dna = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'rule': parsed_dna.rule,
                'parsed': parsed_dna.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(parsed_dna)
            flat['dna'] = dna_str
            flat['rule'] = parsed_dna.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = Outcome.SUCCESS
            new_ledger_entries[idempotency_key] = {
                'terminal_outcome': outcome.name,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            log_observability(correlation_id, "Process DNA", outcome, data={"dna": dna_str})

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = Outcome.ERROR
            new_ledger_entries[idempotency_key] = {
                'terminal_outcome': outcome.name,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'error': str(e)
            }
            log_observability(correlation_id, "Process DNA", outcome, data={"dna": dna_str, "error": str(e)})

        new_processed_count += 1

    if new_processed_count > 0:
        ledger.update(new_ledger_entries)

        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination

        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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

                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                log_observability(correlation_id, "Persistence", Outcome.ERROR, data={"error": str(e)})
                raise PersistenceError("Failed to write output files atomically") from e

    latency = int((time.time() - start_time) * 1000)
    log_observability(correlation_id, "Batch End", Outcome.END, latency_ms=latency, data={"processed": new_processed_count})

if __name__ == '__main__':
    main()
