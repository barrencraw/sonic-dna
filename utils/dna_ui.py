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

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file replacement fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when ledger persistence fails."""
    pass

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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger_atomic(ledger_path, ledger):
    folder = os.path.dirname(ledger_path)
    ensure_folder(folder)
    with tempfile.TemporaryDirectory(dir=folder) as tmp_dir:
        tmp_ledger = os.path.join(tmp_dir, 'ledger.tmp')
        try:
            with open(tmp_ledger, 'w', encoding='utf-8') as f:
                json.dump(ledger, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_ledger, ledger_path)
        except Exception as e:
            raise LedgerSaveError(f"Failed to atomically save ledger: {e}") from e

def log_structured(step, outcome, correlation_id, latency_ms=0.0, idempotency_key=None, extra=None):
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "chain_name": "dna_batch_parser",
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2)
    }
    if idempotency_key is not None:
        log_entry["idempotency_key"] = idempotency_key
    if extra:
        log_entry.update(extra)
    print(f"[{log_entry['timestamp']}] [dna_batch_parser] step={step} outcome={outcome} correlation_id={correlation_id} "
          f"latency_ms={log_entry['latency_ms']}"
          + (f" key={idempotency_key}" if idempotency_key else "")
          + (f" {extra}" if extra else ""))

def run_batch(correlation_id=None):
    start_time = time.time()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    log_structured(
        step="START",
        outcome="ok",
        correlation_id=correlation_id,
        latency_ms=0.0
    )

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        elapsed = (time.time() - start_time) * 1000.0
        log_structured(
            step="COMPLETE",
            outcome="skipped_no_input",
            correlation_id=correlation_id,
            latency_ms=elapsed
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000.0
        log_structured(
            step="LOAD_RULES",
            outcome="error",
            correlation_id=correlation_id,
            latency_ms=elapsed,
            extra={"error": str(e)}
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000.0
        log_structured(
            step="READ_INPUT",
            outcome="error",
            correlation_id=correlation_id,
            latency_ms=elapsed,
            extra={"error": str(e)}
        )
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        elapsed = (time.time() - start_time) * 1000.0
        log_structured(
            step="COMPLETE",
            outcome="skipped_empty_input",
            correlation_id=correlation_id,
            latency_ms=elapsed
        )
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
        now_ms = (time.time() - start_time) * 1000.0

        if idempotency_key in ledger:
            terminal_outcome = ledger[idempotency_key].get('terminal_outcome', 'unknown')
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
            log_structured(
                step="DEDUPE",
                outcome="dedupe_hit",
                correlation_id=correlation_id,
                latency_ms=now_ms,
                idempotency_key=idempotency_key,
                extra={"terminal_outcome": terminal_outcome}
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
        log_structured(
            step="DEDUPE",
            outcome="dedupe_miss",
            correlation_id=correlation_id,
            latency_ms=now_ms,
            idempotency_key=idempotency_key
        )

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

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        parse_latency = (time.time() - start_time) * 1000.0
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'correlation_id': correlation_id
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        log_structured(
            step="PARSE",
            outcome=outcome,
            correlation_id=correlation_id,
            latency_ms=parse_latency,
            idempotency_key=idempotency_key
        )
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # Only perform writes if new items were processed
    if new_processed_count > 0:
        persist_start = time.time()
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
                persist_latency = (time.time() - start_time) * 1000.0
                log_structured(
                    step="PERSIST",
                    outcome="error",
                    correlation_id=correlation_id,
                    latency_ms=persist_latency,
                    extra={"error": str(e)}
                )
                raise PersistenceError("Failed to write output files atomically") from e

        # Save ledger atomically
        save_ledger_atomic(ledger_path, ledger)
        persist_latency = (time.time() - start_time) * 1000.0
        log_structured(
            step="PERSIST",
            outcome="ok",
            correlation_id=correlation_id,
            latency_ms=persist_latency,
            extra={"new_records": new_processed_count}
        )

    total_latency = (time.time() - start_time) * 1000.0
    log_structured(
        step="COMPLETE",
        outcome="ok",
        correlation_id=correlation_id,
        latency_ms=total_latency,
        extra={"new_processed": new_processed_count, "total_ledger": len(ledger)}
    )

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

# Maintain backward compatibility alias
main = run_batch

if __name__ == '__main__':
    run_batch()
