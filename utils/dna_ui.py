#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerError(DNAProcessingError):
    """Base class for ledger errors."""
    pass

class LedgerLoadError(LedgerError):
    """Raised when loading ledger fails."""
    pass

class LedgerSaveError(LedgerError, PersistenceError):
    """Raised when saving ledger fails."""
    pass


def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequence_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_sequence_list.append(s)
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
                return json.load(f)
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Failed to parse ledger JSON: {ledger_path}") from e
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}


def save_ledger(ledger_path, ledger):
    ledger_dir = os.path.dirname(ledger_path)
    ensure_folder(ledger_dir)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=ledger_dir, delete=False, encoding='utf-8') as tf:
            json.dump(ledger, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name
        os.replace(temp_name, ledger_path)
    except Exception as e:
        if temp_name and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically to {ledger_path}") from e


def log_structured(correlation_id, step, outcome, latency_ms=0.0, actor_id="orchestrator", idempotency_key=None, outcome_detail=None):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        latency_ms = float(latency_ms)
    except (TypeError, ValueError):
        latency_ms = 0.0

    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": "dna_batch_parsing_chain",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")


def run_batch(correlation_id=None):
    start_time = time.time()
    if correlation_id is None:
        correlation_id = "manual"

    # Define paths once at beginning to prevent UnboundLocalError
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            step="check_input_file",
            outcome="error",
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            step="init_calculator",
            outcome="error",
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=f"Could not load rules: {str(e)}"
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequence list
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            step="read_input",
            outcome="error",
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=f"Failed to read input file: {str(e)}"
        )
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            step="process_batch",
            outcome="skipped",
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail="No DNA strings found in toSequence.txt"
        )
        return

    try:
        ledger = load_ledger(ledger_path)
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            step="load_ledger",
            outcome="error",
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=f"Failed to load ledger: {str(e)}"
        )
        raise

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
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            terminal_outcome_val = ledger[idempotency_key].get('terminal_outcome', 'success')
            log_structured(
                correlation_id=correlation_id,
                step="deduplicate_check",
                outcome="skipped",
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit. Previous outcome: {terminal_outcome_val}"
            )
            continue

        item_start_time = time.time()
        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_sequence,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "error"

        # Record outcome inside loop to maintain idempotency
        timestamp_utc = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': timestamp_utc
        }

        log_structured(
            correlation_id=correlation_id,
            step="parse_sequence",
            outcome=outcome,
            latency_ms=(time.time() - item_start_time) * 1000,
            idempotency_key=idempotency_key,
            outcome_detail=f"Parsed {dna_sequence} with result {outcome}"
        )
        new_processed_count += 1

    if new_processed_count > 0:
        # Save ledger and write output files atomically!
        save_ledger(ledger_path, ledger)

        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            try:
                # 1) Write JSON output to temp
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) Write CSV output to temp
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    log_structured(
        correlation_id=correlation_id,
        step="batch_completed",
        outcome="success",
        latency_ms=(time.time() - start_time) * 1000,
        outcome_detail=f"Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}"
    )

# Alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
