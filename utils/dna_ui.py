#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from typing import List, Optional
from utils.dna_calculator import DNACalculator, RuleParseError
from utils.dtos import DNAResult, ProcessingOutcome
from utils.observability import StructuredLogger

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

def run_batch(correlation_id: Optional[str] = None):
    """
    Main batch processing chain.
    """
    logger = StructuredLogger(chain_name="dna_batch_processing", correlation_id=correlation_id)
    logger.start()
    start_time = time.time()

    try:
        # Determine file paths
        project_root = os.getcwd()
        raw_folder = os.path.join(project_root, 'data', 'raw')
        output_folder = os.path.join(project_root, 'data', 'output')
        ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
        ensure_folder(output_folder)

        input_file = os.path.join(raw_folder, 'toSequence.txt')
        if not os.path.isfile(input_file):
            logger.terminal(step="initialization", outcome="error", message=f"Input file not found: {input_file}")
            return

        # Instantiate calculator
        try:
            calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
        except Exception as e:
            logger.terminal(step="rule_loading", outcome="error", error=str(e))
            raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

        # Read DNA strings
        try:
            dna_list = read_input_file(input_file)
        except Exception as e:
            logger.terminal(step="input_reading", outcome="error", error=str(e))
            raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

        if not dna_list:
            logger.terminal(step="input_reading", outcome="success", message="No DNA strings found")
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
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                logger.log(step="process_item", outcome=ProcessingOutcome.DEDUPE.value, idempotency_key=idempotency_key)
                continue

            try:
                result: DNAResult = calculator.parse(dna_str)
                result.outcome = ProcessingOutcome.SUCCESS

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

                logger.log(step="process_item", outcome=ProcessingOutcome.SUCCESS.value, idempotency_key=idempotency_key, rule=result.rule)

            except RuleParseError as e:
                result = DNAResult(dna=dna_str, error=str(e), outcome=ProcessingOutcome.ERROR)

                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                logger.log(step="process_item", outcome=ProcessingOutcome.ERROR.value, idempotency_key=idempotency_key, error=str(e))

            # Update ledger for each item
            ledger[idempotency_key] = {
                'terminal_outcome': result.outcome.value,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1

        if new_processed_count > 0:
            # ATOMIC WRITE PATTERN
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')
                tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

                try:
                    # 1) Write JSON
                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    # 2) Write CSV
                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())

                    # 3) Write Ledger
                    with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                        json.dump(ledger, lf, indent=2)
                        lf.flush()
                        os.fsync(lf.fileno())

                    # 4) Atomic renames
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)
                    os.replace(tmp_ledger, ledger_path)

                except Exception as e:
                    logger.terminal(step="persistence", outcome="error", error=str(e))
                    raise PersistenceError("Failed to write output files atomically") from e

        latency = (time.time() - start_time) * 1000
        logger.terminal(step="complete", outcome="success", new_items=new_processed_count, latency_ms=latency)

    except Exception as e:
        latency = (time.time() - start_time) * 1000
        logger.terminal(step="fatal_error", outcome="error", error=str(e), latency_ms=latency)
        raise

def main():
    """Legacy entry point for backward compatibility."""
    run_batch()

if __name__ == '__main__':
    main()
