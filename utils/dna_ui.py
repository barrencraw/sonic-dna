#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
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

class BatchResult:
    def __init__(self, status, new_processed_count=0, total_in_ledger=0, error=None):
        self.status = status  # "SUCCESS", "NO_NEW_ITEMS", "FAILED"
        self.new_processed_count = new_processed_count
        self.total_in_ledger = total_in_ledger
        self.error = error

    def __repr__(self):
        return f"BatchResult(status={self.status}, new_processed_count={self.new_processed_count}, total_in_ledger={self.total_in_ledger}, error={self.error})"

def log_structured(correlation_id, step, outcome, latency_ms=0, actor_id="batch_worker", idempotency_key=None, outcome_detail=None):
    import datetime
    # Format timestamp with Z suffix to denote UTC timezone
    if hasattr(datetime, "timezone"):
        timestamp_str = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
    else:
        timestamp_str = datetime.datetime.utcnow().isoformat() + 'Z'
    log_data = {
        "timestamp": timestamp_str,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "batch_worker",
        "chain_name": "dna_batch_parser",
        "step": step,
        "outcome": outcome,
        "latency_ms": int(latency_ms),
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    dir_name = os.path.dirname(ledger_path)
    ensure_folder(dir_name)
    temp_fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix="ledger_", suffix=".json")
    try:
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, ledger_path)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically: {e}") from e

def run_batch(correlation_id=None):
    start_time = time.time()

    # 1. Log start
    log_structured(correlation_id, "start", "pending")

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, "file_check", "skipped", latency_ms=int((time.time() - start_time) * 1000), outcome_detail="Input file not found")
        return BatchResult(status="NO_NEW_ITEMS", new_processed_count=0, total_in_ledger=0)

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, "load_rules", "error", latency_ms=int((time.time() - start_time) * 1000), outcome_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, "read_input", "error", latency_ms=int((time.time() - start_time) * 1000), outcome_detail=str(e))
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    ledger = load_ledger(ledger_path)

    if not dna_sequence_list:
        log_structured(correlation_id, "read_input", "skipped", latency_ms=int((time.time() - start_time) * 1000), outcome_detail="No DNA strings found")
        return BatchResult(status="NO_NEW_ITEMS", new_processed_count=0, total_in_ledger=len(ledger))

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
                for entry in parsed_json:
                    if 'dna' in entry:
                        entry['dna_sequence'] = entry.pop('dna')
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
                    fieldnames = list(reader.fieldnames)
                    if 'dna' in fieldnames:
                        fieldnames.remove('dna')
                        fieldnames.append('dna_sequence')
                    all_flattened_keys = set(fieldnames)
                    for row in reader:
                        if 'dna' in row:
                            row['dna_sequence'] = row.pop('dna')
                        csv_rows.append(row)
        except Exception:
            pass

    from utils.dna_calculator import RuleParseError

    new_processed_count = 0
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(
                correlation_id=correlation_id,
                step="process_item",
                outcome="skipped",
                idempotency_key=idempotency_key,
                outcome_detail=f"dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}"
            )
            continue

        item_start_time = time.time()
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

        item_latency = int((time.time() - item_start_time) * 1000)
        log_structured(
            correlation_id=correlation_id,
            step="process_item",
            outcome=outcome,
            idempotency_key=idempotency_key,
            latency_ms=item_latency,
            outcome_detail="" if outcome == "success" else f"RuleParseError"
        )
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
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
                log_structured(correlation_id, "write_output", "error", latency_ms=int((time.time() - start_time) * 1000), outcome_detail=str(e))
                raise PersistenceError("Failed to write output files atomically") from e

        # Save ledger atomically (atomic write inside save_ledger)
        try:
            save_ledger(ledger_path, ledger)
        except Exception as e:
            log_structured(correlation_id, "save_ledger", "error", latency_ms=int((time.time() - start_time) * 1000), outcome_detail=str(e))
            raise

    total_latency = int((time.time() - start_time) * 1000)
    log_structured(
        correlation_id=correlation_id,
        step="complete",
        outcome="success" if new_processed_count > 0 else "skipped",
        latency_ms=total_latency,
        outcome_detail=f"Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}"
    )

    if new_processed_count > 0:
        return BatchResult(status="SUCCESS", new_processed_count=new_processed_count, total_in_ledger=len(ledger))
    else:
        return BatchResult(status="NO_NEW_ITEMS", new_processed_count=0, total_in_ledger=len(ledger))

main = run_batch

if __name__ == '__main__':
    run_batch()
