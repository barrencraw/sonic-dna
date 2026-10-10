#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

# Exception Taxonomy
class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input files fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading the processed ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing or moving output files fails atomically."""
    pass


def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None):
    """
    Emits structured JSON logs prefixed with JSON_LOG:
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")


def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_path}") from e
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
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except Exception as e:
            raise LedgerLoadError(f"Failed to load processed ledger from {ledger_path}: {e}") from e
    return {}


def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        raise LedgerSaveError(f"Failed to save processed ledger to {ledger_path}: {e}") from e


def run_batch(correlation_id=None):
    start_time = time.time()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    actor_id = "batch_parser"
    chain_name = "dna_batch_parser"

    log_structured(correlation_id, actor_id, chain_name, "start", "success")

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_structured(correlation_id, actor_id, chain_name, "read_input", "error", latency_ms=int((time.time() - start_time) * 1000), outcome_detail="Input file not found")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, actor_id, chain_name, "load_rules", "error", latency_ms=int((time.time() - start_time) * 1000), outcome_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_list = read_input_file(input_file)
    log_structured(correlation_id, actor_id, chain_name, "read_input", "success", outcome_detail=f"Found {len(dna_list)} DNA sequences")

    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        log_structured(correlation_id, actor_id, chain_name, "end", "success", latency_ms=int((time.time() - start_time) * 1000), outcome_detail="No sequences to process")
        return

    ledger = load_ledger(ledger_path)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            log_structured(correlation_id, actor_id, chain_name, "dedupe_check", "skipped", idempotency_key=idempotency_key, outcome_detail=ledger[idempotency_key]['terminal_outcome'])
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
        log_structured(correlation_id, actor_id, chain_name, "dedupe_check", "miss", idempotency_key=idempotency_key)

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
            outcome = "success"

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
            outcome = f"error: {str(e)}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_structured(correlation_id, actor_id, chain_name, "parse_sequence", "success" if outcome == "success" else "error", idempotency_key=idempotency_key, outcome_detail=outcome)
        new_processed_count += 1

    if new_processed_count > 0:
        # Save ledger
        save_ledger(ledger_path, ledger)

        # ATOMIC WRITE PATTERN
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

                log_structured(correlation_id, actor_id, chain_name, "atomic_write", "success", outcome_detail=f"Wrote {new_processed_count} new entries")

            except Exception as e:
                log_structured(correlation_id, actor_id, chain_name, "atomic_write", "error", outcome_detail=str(e))
                raise AtomicWriteError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

    log_structured(correlation_id, actor_id, chain_name, "end", "success", latency_ms=int((time.time() - start_time) * 1000), outcome_detail=f"Processed {new_processed_count} sequences")

main = run_batch

if __name__ == '__main__':
    main()
