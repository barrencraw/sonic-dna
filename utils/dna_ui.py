#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError


# ─── ERROR TAXONOMY ───────────────────────────────────────────────────────────

class DNAProcessingError(Exception):
    """Base exception for all DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rule files or DNACalculator cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input sequence file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base exception for persistence and output writing errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing the processed ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when staging, flushing, or replacing output files fails."""
    pass


# ─── STRUCTURED TELEMETRY LOGGING ──────────────────────────────────────────────

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key=None, outcome_detail=None):
    """
    Emits single-line structured JSON log prefixed with JSON_LOG:
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name or "dna_batch_parse",
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail or {}
    }
    print(f"JSON_LOG:{json.dumps(log_entry)}")


# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence string.
    Returns a list of DNA sequence strings (stripped, non-empty).
    """
    dna_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file {input_path}: {e}") from e
    return dna_list

def flatten_parsed(rule_name, values_dict, parent_key=''):
    """
    Given nested values_dict, flatten into { 'rule.sub1.sub2': value, ... }.
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
                content = json.load(f)
                return content if isinstance(content, dict) else {}
        except Exception as e:
            raise LedgerLoadError(f"Corrupted or invalid ledger file at {ledger_path}: {e}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e


# ─── CORE BATCH PARSER ────────────────────────────────────────────────────────

def run_batch(correlation_id=None):
    start_time = time.time()
    cid = correlation_id or str(uuid.uuid4())
    actor = "batch_parser"
    chain = "dna_batch_parse"

    log_structured(cid, actor, chain, "start", "success", 0.0)

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(cid, actor, chain, "read_input", "error", (time.time() - start_time) * 1000,
                       outcome_detail={"reason": f"Input file not found: {input_file}"})
        print(f"[ERROR] Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(cid, actor, chain, "load_rules", "error", (time.time() - start_time) * 1000,
                       outcome_detail={"reason": str(e)})
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_list = read_input_file(input_file)
    if not dna_list:
        log_structured(cid, actor, chain, "read_input", "skipped", (time.time() - start_time) * 1000,
                       outcome_detail={"reason": "No DNA sequences found in input file"})
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)

    # 1) Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                content = json.load(jf)
                if isinstance(content, list):
                    parsed_json = content
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
            term_outcome = ledger[idempotency_key].get('terminal_outcome', 'unknown')
            log_structured(cid, actor, chain, "dedupe_check", "skipped", (time.time() - start_time) * 1000,
                           idempotency_key=idempotency_key, outcome_detail={"terminal_outcome": term_outcome})
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            continue

        step_start = time.time()
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'dna_sequence': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['dna_sequence'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'dna_sequence': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        new_processed_count += 1

        log_structured(cid, actor, chain, "parse_sequence", outcome, (time.time() - step_start) * 1000,
                       idempotency_key=idempotency_key, outcome_detail={"outcome": outcome})
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")

    if new_processed_count > 0:
        # Save updated ledger
        save_ledger(ledger_path, ledger)

        # Atomic write for outputs
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            try:
                # 1) Write JSON to temp
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) Write CSV to temp
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Atomic replace
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                log_structured(cid, actor, chain, "atomic_write", "error", (time.time() - start_time) * 1000,
                               outcome_detail={"reason": str(e)})
                raise AtomicWriteError(f"Failed to write output files atomically: {e}") from e

    total_latency = (time.time() - start_time) * 1000
    log_structured(cid, actor, chain, "end", "success", total_latency,
                   outcome_detail={"new_processed": new_processed_count, "total_ledger": len(ledger)})

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

# Maintain main alias for backwards-compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
