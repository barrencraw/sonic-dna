#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import datetime
from dataclasses import dataclass
from utils.dna_calculator import DNACalculator, RuleParseError

@dataclass
class BatchResult:
    status: str          # 'SUCCESS' or 'NO_NEW_ITEMS'
    processed_count: int
    total_ledger_items: int

# Exception Taxonomy
class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input file cannot be read."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence/storage errors."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when writing the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass


def log_structured(step, outcome, latency_ms=0, correlation_id=None, actor_id="orchestrator", chain_name="dna_batch_parser", idempotency_key=None, outcome_detail=None):
    """
    Standardized structured logging. Emits JSON logs with the JSON_LOG: prefix.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    log_entry = {
        "timestamp": timestamp_str,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")


def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
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
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_ledger(ledger_path, ledger):
    ledger_dir = os.path.dirname(ledger_path)
    if ledger_dir:
        ensure_folder(ledger_dir)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=ledger_dir or ".", prefix="ledger_", suffix=".tmp")
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


def run_batch(correlation_id=None):
    # Determine file paths
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
            step="initialization",
            outcome="refused",
            correlation_id=correlation_id,
            outcome_detail=f"Input file not found: {input_file}"
        )
        raise InputReadError(f"Input file not found: {input_file}")

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            step="rules_loading",
            outcome="error",
            correlation_id=correlation_id,
            outcome_detail=str(e)
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        log_structured(
            step="input_reading",
            outcome="skipped",
            correlation_id=correlation_id,
            outcome_detail="No DNA sequences found in toSequence.txt"
        )
        return BatchResult(
            status="NO_NEW_ITEMS",
            processed_count=0,
            total_ledger_items=0
        )

    ledger = load_ledger(ledger_path)

    # 1) Load existing JSON output
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
    start_time = time.time()

    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(
                step="deduplication",
                outcome="skipped",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplication hit. Terminal outcome: {ledger[idempotency_key]['terminal_outcome']}"
            )
            continue

        log_structured(
            step="parsing",
            outcome="processing",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key
        )

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "error"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

        log_structured(
            step="parsing",
            outcome=outcome,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key
        )

    if new_processed_count > 0:
        # Save ledger atomically
        save_ledger(ledger_path, ledger)

        # ATOMIC WRITE PATTERN FOR OUTPUTS:
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
                raise AtomicWriteError("Failed to write output files atomically") from e

    latency_ms = int((time.time() - start_time) * 1000)
    status = "SUCCESS" if new_processed_count > 0 else "NO_NEW_ITEMS"

    log_structured(
        step="execution",
        outcome=status.lower(),
        latency_ms=latency_ms,
        correlation_id=correlation_id,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

    return BatchResult(
        status=status,
        processed_count=new_processed_count,
        total_ledger_items=len(ledger)
    )

# Backward compatibility alias
main = run_batch

if __name__ == '__main__':
    run_batch()
