#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

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

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when writing or moving ledger fails."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
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
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    ledger_dir = os.path.dirname(ledger_path)
    ensure_folder(ledger_dir)
    # The ledger file is saved atomically using a temporary file write, flush, fsync, and replace sequence
    tmp_fd, tmp_path = tempfile.mkstemp(dir=ledger_dir, prefix=".ledger_tmp_")
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # Ignore if OS/filesystem doesn't support fsync on temp files
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically: {e}") from e

def log_structured(correlation_id, step, outcome, latency_ms=0, actor_id="system", idempotency_key=None, outcome_detail=None):
    """
    Standardized structured logging with UTC ISO 8601 millisecond timestamps.
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id if correlation_id is not None else "N/A",
        "actor_id": actor_id if actor_id is not None else "system",
        "chain_name": "dna_batch_parsing",
        "step": step,
        "outcome": outcome,
        "latency_ms": int(latency_ms),
        "idempotency_key": idempotency_key if idempotency_key is not None else "N/A",
        "outcome_detail": outcome_detail if outcome_detail is not None else "N/A"
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None):
    start_time = time.perf_counter()
    log_structured(correlation_id, step="start_batch", outcome="success")

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_structured(correlation_id, step="complete_batch", outcome="error", latency_ms=latency_ms, outcome_detail=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_structured(correlation_id, step="complete_batch", outcome="error", latency_ms=latency_ms, outcome_detail=f"Could not load rules: {e}")
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_structured(correlation_id, step="complete_batch", outcome="error", latency_ms=latency_ms, outcome_detail=f"Failed to read input file: {e}")
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_structured(correlation_id, step="complete_batch", outcome="success", latency_ms=latency_ms, outcome_detail="No DNA sequences found in toSequence.txt")
        return

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
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(
                correlation_id,
                step="dedupe",
                outcome=DNAStatus.SKIPPED,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated: already processed with terminal_outcome={ledger[idempotency_key]['terminal_outcome']}"
            )
            continue

        step_start = time.perf_counter()
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
            outcome = DNAStatus.SUCCESS
            detail = "Successfully parsed DNA sequence"

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
            outcome = DNAStatus.ERROR
            detail = str(e)

        step_latency = (time.perf_counter() - step_start) * 1000
        log_structured(
            correlation_id,
            step="parse_sequence",
            outcome=outcome,
            latency_ms=step_latency,
            idempotency_key=idempotency_key,
            outcome_detail=detail
        )

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    # Rewrite outputs and ledger only if we processed new sequences
    if new_processed_count > 0:
        # Save ledger
        save_ledger(ledger_path, ledger)

        # Atomic Write
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            try:
                # 1) Write JSON output to temp
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    try:
                        os.fsync(jf.fileno())
                    except OSError:
                        pass

                # 2) Write CSV output to temp
                # Ensure canonical key 'dna_sequence'
                all_flattened_keys.add('dna_sequence')
                if 'dna' in all_flattened_keys:
                    all_flattened_keys.remove('dna')
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        if 'dna' in row and 'dna_sequence' not in row:
                            row['dna_sequence'] = row['dna']
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    try:
                        os.fsync(cf.fileno())
                    except OSError:
                        pass

                # 3) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    latency_ms = (time.perf_counter() - start_time) * 1000
    log_structured(
        correlation_id,
        step="complete_batch",
        outcome="success",
        latency_ms=latency_ms,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

main = run_batch

if __name__ == '__main__':
    run_batch()
