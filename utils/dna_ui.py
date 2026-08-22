#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# ─── DOMAIN & TERMINAL STATES ──────────────────────────────────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"

# ─── EXCEPTION TAXONOMY ────────────────────────────────────────────────────────

class DNAProcessingError(Exception):
    """Base exception for all DNA processing failures."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input files cannot be located or read."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when parsing rule definitions cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base exception for data persistence failures."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when the processing ledger fails to load or parse."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file persistence operations fail."""
    pass


# ─── STRUCTURED OBSERVABILITY ──────────────────────────────────────────────────

def log_structured(chain_name: str, step: str, outcome: str, latency_ms: float = 0.0,
                   correlation_id: str = None, actor_id: str = "system",
                   idempotency_key: str = None, outcome_detail: str = ""):
    """Emits standardized structured JSON logs for decision points and terminal states."""
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key or "",
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")


# ─── UTILITIES ─────────────────────────────────────────────────────────────────

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    if not os.path.isfile(input_path):
        raise InputReadError(f"Input file not found: {input_path}")
    dna_sequence_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequence_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file {input_path}: {e}") from e
    return dna_sequence_list

def flatten_parsed(rule_name, values_dict, parent_key=''):
    """
    Given nested values_dict, flatten into { 'rule.sub1.sub2': value, ... }.
    Useful for CSV export.
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
        except Exception as e:
            raise LedgerLoadError(f"Failed to load or parse ledger file {ledger_path}: {e}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise AtomicWriteError(f"Failed to save ledger {ledger_path}: {e}") from e


# ─── MAIN BATCH PROCESSOR ──────────────────────────────────────────────────────

def run_batch(correlation_id=None):
    start_time = time.time()
    chain_name = "dna_batch_parser"
    actor_id = "batch_worker"
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    log_structured(chain_name=chain_name, step="start", outcome="initiated",
                   correlation_id=correlation_id, actor_id=actor_id)

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    rules_folder = os.path.join(project_root, 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        err = RuleLoadError(f"Could not load rules from {rules_folder}: {e}")
        log_structured(chain_name=chain_name, step="load_rules", outcome="error",
                       latency_ms=(time.time()-start_time)*1000, correlation_id=correlation_id,
                       actor_id=actor_id, outcome_detail=str(err))
        raise err from e

    # Read DNA sequence list
    try:
        dna_sequence_list = read_input_file(input_file)
    except InputReadError as e:
        log_structured(chain_name=chain_name, step="read_input", outcome="error",
                       latency_ms=(time.time()-start_time)*1000, correlation_id=correlation_id,
                       actor_id=actor_id, outcome_detail=str(e))
        raise e

    if not dna_sequence_list:
        log_structured(chain_name=chain_name, step="read_input", outcome=DNAStatus.SKIPPED.value,
                       latency_ms=(time.time()-start_time)*1000, correlation_id=correlation_id,
                       actor_id=actor_id, outcome_detail="No DNA sequences found in input file")
        return

    ledger = load_ledger(ledger_path)

    # Load existing JSON output
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

    # Load existing CSV rows
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
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(chain_name=chain_name, step="deduplicate", outcome=DNAStatus.SKIPPED.value,
                           correlation_id=correlation_id, actor_id=actor_id,
                           idempotency_key=idempotency_key,
                           outcome_detail=f"Terminal outcome: {ledger[idempotency_key].get('terminal_outcome')}")
            continue

        item_start = time.time()
        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,  # Backwards compatibility
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_sequence
            flat['dna'] = dna_sequence  # Backwards compatibility
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            terminal_status = DNAStatus.SUCCESS.value
            err_detail = ""

        except RuleParseError as e:
            parsed_json.append({
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,  # Backwards compatibility
                'error': str(e)
            })
            flat = {
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,  # Backwards compatibility
                'error': str(e)
            }
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            terminal_status = DNAStatus.ERROR.value
            err_detail = str(e)

        ledger[idempotency_key] = {
            'terminal_outcome': terminal_status,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

        log_structured(chain_name=chain_name, step="parse_sequence", outcome=terminal_status,
                       latency_ms=(time.time() - item_start) * 1000, correlation_id=correlation_id,
                       actor_id=actor_id, idempotency_key=idempotency_key, outcome_detail=err_detail)

    # Atomic write pattern for persistence
    if new_processed_count > 0:
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

        save_ledger(ledger_path, ledger)

    log_structured(chain_name=chain_name, step="complete", outcome="completed",
                   latency_ms=(time.time() - start_time) * 1000, correlation_id=correlation_id,
                   actor_id=actor_id, outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total ledger size: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    run_batch()
