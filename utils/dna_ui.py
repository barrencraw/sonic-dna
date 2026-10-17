#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
from utils.dna_calculator import DNACalculator, RuleParseError

# Exception Taxonomy
class DNAProcessingError(Exception):
    """Base exception for all DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when output file atomic write or replacement fails."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input DNA sequences fails."""
    pass

def log_structured(step, outcome, latency_ms=0, correlation_id=None, actor_id="batch_parser",
                   chain_name="dna_batch_parsing", idempotency_key=None, outcome_detail=None):
    """
    Emits structured JSON logs prefixed with 'JSON_LOG:'.
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    log_payload = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_payload)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
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
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise PersistenceError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None):
    """
    Core batch processing logic with deduplication (idempotency)
    and atomic file writes.
    """
    start_time = time.time()
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    log_structured(
        step="start",
        outcome="success",
        correlation_id=correlation_id,
        outcome_detail="Initializing DNA batch parsing"
    )

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            step="check_input",
            outcome="skipped",
            correlation_id=correlation_id,
            outcome_detail=f"Input file not found: {input_file}"
        )
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    rules_folder = os.path.join(project_root, 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        log_structured(
            step="load_rules",
            outcome="error",
            correlation_id=correlation_id,
            outcome_detail=str(e)
        )
        raise RuleLoadError(f"Could not load rules from {rules_folder}") from e

    dna_list = read_input_file(input_file)
    if not dna_list:
        log_structured(
            step="read_input",
            outcome="skipped",
            correlation_id=correlation_id,
            outcome_detail="No DNA strings found in toSequence.txt"
        )
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                loaded = json.load(jf)
                if isinstance(loaded, list):
                    parsed_json = loaded
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
        seq_start = time.time()

        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', 'unknown')
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(
                step="skipped",
                outcome="skipped",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplication hit with terminal_outcome={term_outcome}"
            )
            continue

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
            outcome = "success"
            detail = f"Successfully parsed rule {result['rule']}"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "error"
            detail = str(e)

        seq_latency = (time.time() - seq_start) * 1000.0
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")

        log_structured(
            step="parse_sequence",
            outcome=outcome,
            latency_ms=seq_latency,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            outcome_detail=detail
        )
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # If new DNA items were processed or if output files don't exist yet, perform atomic write.
    if new_processed_count > 0 or not (os.path.exists(json_output_path) and os.path.exists(csv_output_path)):
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

        # Save ledger upon successful atomic write
        save_ledger(ledger_path, ledger)

    total_latency = (time.time() - start_time) * 1000.0
    log_structured(
        step="complete",
        outcome="success",
        latency_ms=total_latency,
        correlation_id=correlation_id,
        outcome_detail=f"Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}"
    )

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

# Maintain backward compatibility alias
main = run_batch

if __name__ == '__main__':
    main()
