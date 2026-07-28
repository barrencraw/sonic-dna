#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- CONSTANTS & ENUMS ---

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# --- CUSTOM EXCEPTIONS ---

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
    """Raised when saving the ledger fails."""
    pass

# --- UTILITY FUNCTIONS ---

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

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    """
    Emits standardized JSON logs prefixed with 'JSON_LOG:' to stdout.
    Uses precise ISO 8601 UTC timestamp formatting.
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_entry = {
        'timestamp': timestamp,
        'correlation_id': correlation_id or "N/A",
        'actor_id': actor_id or "system",
        'chain_name': chain_name or "DNA_Batch_Parsing",
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key or "N/A",
        'outcome_detail': outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    """
    Saves the ledger atomically using a temporary file, flush, fsync, and replace sequence.
    Handles save exceptions gracefully, cleaning up any partial file before re-raising LedgerSaveError.
    """
    dir_name = os.path.dirname(ledger_path)
    ensure_folder(dir_name)
    fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix="ledger_", suffix=".json")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
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

# --- CORE BATCH PROCESSOR ---

def run_batch(correlation_id=None):
    start_time = time.time()
    actor_id = "system"
    chain_name = "DNA_Batch_Parsing"

    # Start log
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step="batch_start",
        outcome=DNAStatus.SUCCESS,
        latency_ms=0,
        idempotency_key=None,
        outcome_detail="Starting DNA batch processing"
    )

    # Determine file paths (Define output paths early once to prevent UnboundLocalError)
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="check_input",
            outcome=DNAStatus.ERROR,
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail=f"Input file not found: {input_file}"
        )
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="load_rules",
            outcome=DNAStatus.ERROR,
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail=f"Could not load rules: {str(e)}"
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.ERROR,
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail=f"Failed to read input file: {str(e)}"
        )
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.SKIPPED,
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail="No DNA strings found in toSequence.txt"
        )
        print("[WARN] No DNA strings found in toSequence.txt")
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

    for dna_str in dna_list:
        step_start_time = time.time()
        idempotency_key = dna_str

        # Check idempotency: skip any DNA string that already exists in ledger with terminal outcome ('success' or 'error' prefix)
        if idempotency_key in ledger:
            terminal_outcome = ledger[idempotency_key].get('terminal_outcome')
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step="process_dna",
                outcome=DNAStatus.SKIPPED,
                latency_ms=int((time.time() - step_start_time) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplication hit. Already processed with outcome: {terminal_outcome}"
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
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
            outcome = DNAStatus.SUCCESS
            detail = "Parsed DNA string successfully"

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
            outcome = DNAStatus.ERROR
            detail = f"Parse error: {str(e)}"

        # Save to ledger
        current_utc_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': current_utc_time
        }

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step="process_dna",
            outcome=outcome,
            latency_ms=int((time.time() - step_start_time) * 1000),
            idempotency_key=idempotency_key,
            outcome_detail=detail
        )
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # Rewrite output files and save ledger ONLY if new_processed_count > 0
    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)
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
                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name=chain_name,
                    step="write_outputs",
                    outcome=DNAStatus.ERROR,
                    latency_ms=int((time.time() - start_time) * 1000),
                    idempotency_key=None,
                    outcome_detail=f"Atomic write failed: {str(e)}"
                )
                raise PersistenceError("Failed to write output files atomically") from e

        # Save ledger atomically (raises LedgerSaveError on failure)
        save_ledger(ledger_path, ledger)

    # End log
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step="batch_end",
        outcome=DNAStatus.SUCCESS,
        latency_ms=int((time.time() - start_time) * 1000),
        idempotency_key=None,
        outcome_detail=f"Batch finished. Processed {new_processed_count} new DNA strings."
    )
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

# Maintain backward compatibility alias
main = run_batch

if __name__ == '__main__':
    run_batch()
