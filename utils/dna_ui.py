#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

# ─── EXCEPTIONS ───────────────────────────────────────────────────────────────

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

# ─── STRUCTURED TELEMETRY ─────────────────────────────────────────────────────

def log_structured(correlation_id, actor_id, step, outcome, latency_ms=0.0, idempotency_key=None, outcome_detail=None):
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": "dna_batch_parsing",
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key or "batch",
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

# ─── UTILITIES ────────────────────────────────────────────────────────────────

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
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    try:
        ledger_dir = os.path.dirname(os.path.abspath(ledger_path))
        with tempfile.NamedTemporaryFile('w', dir=ledger_dir, delete=False, encoding='utf-8') as tf:
            json.dump(ledger, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_name = tf.name
        os.replace(tmp_name, ledger_path)
    except Exception as e:
        raise PersistenceError(f"Failed to save ledger atomically: {e}") from e

# ─── CORE BATCH PROCESSING ────────────────────────────────────────────────────

def run_batch(correlation_id=None, actor_id="batch_parser"):
    batch_start = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())

    log_structured(correlation_id, actor_id, step="start", outcome="started", latency_ms=0.0)

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_structured(correlation_id, actor_id, step="start", outcome="error", latency_ms=(time.time() - batch_start) * 1000, outcome_detail=f"Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, actor_id, step="start", outcome="error", latency_ms=(time.time() - batch_start) * 1000, outcome_detail=str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(correlation_id, actor_id, step="start", outcome="error", latency_ms=(time.time() - batch_start) * 1000, outcome_detail=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        log_structured(correlation_id, actor_id, step="end", outcome="completed", latency_ms=(time.time() - batch_start) * 1000, outcome_detail="No DNA strings to process")
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
        item_start = time.time()
        idempotency_key = dna_str
        if idempotency_key in ledger:
            terminal_outcome = ledger[idempotency_key].get('terminal_outcome', 'unknown')
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
            log_structured(
                correlation_id, actor_id, step="item_process", outcome="skipped",
                latency_ms=(time.time() - item_start) * 1000, idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated (terminal_outcome={terminal_outcome})"
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
            detail = None

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
            outcome = "error"
            detail = str(e)

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        log_structured(
            correlation_id, actor_id, step="item_process", outcome=outcome,
            latency_ms=(time.time() - item_start) * 1000, idempotency_key=idempotency_key,
            outcome_detail=detail
        )
        new_processed_count += 1

    # ATOMIC WRITE PATTERN: Only write files if new sequences were processed
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

                # 4) Save ledger atomically
                save_ledger(ledger_path, ledger)

                log_structured(
                    correlation_id, actor_id, step="persist", outcome="success",
                    latency_ms=(time.time() - persist_start) * 1000,
                    outcome_detail=f"Committed {new_processed_count} new entries to JSON, CSV, and ledger"
                )

            except Exception as e:
                log_structured(
                    correlation_id, actor_id, step="persist", outcome="error",
                    latency_ms=(time.time() - persist_start) * 1000,
                    outcome_detail=str(e)
                )
                raise PersistenceError("Failed to write output files atomically") from e

    total_latency = (time.time() - batch_start) * 1000
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

    log_structured(
        correlation_id, actor_id, step="end", outcome="completed",
        latency_ms=total_latency,
        outcome_detail=f"Batch finished. New: {new_processed_count}, Total ledger: {len(ledger)}"
    )

# Backward-compatibility alias
main = run_batch

if __name__ == '__main__':
    run_batch()
