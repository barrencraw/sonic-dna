#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import uuid
import tempfile
import shutil
from enum import Enum
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

class InputReadError(DNAProcessingError):
    """Raised when reading inputs fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass

class DNAStatus(str, Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'

class BatchResult:
    def __init__(self, status: str, processed_count: int, total_ledger_items: int):
        self.status = status
        self.processed_count = processed_count
        self.total_ledger_items = total_ledger_items

    def __repr__(self):
        return f"BatchResult(status={self.status!r}, processed_count={self.processed_count}, total_ledger_items={self.total_ledger_items})"

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

def save_ledger(ledger_path, ledger):
    ledger_dir = os.path.dirname(ledger_path)
    ensure_folder(ledger_dir)
    # Write to a temporary file in the same directory to prevent torn writes
    tmp_fd, tmp_path = tempfile.mkstemp(dir=ledger_dir, prefix="ledger_", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        # Clean up partial files
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise LedgerSaveError("Failed to save ledger atomically") from e

def log_structured(step: str, outcome: str, correlation_id: str = None, actor_id: str = "system", chain_name: str = "dna_batch_parser", latency_ms: float = 0.0, idempotency_key: str = None, outcome_detail: str = None):
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_entry = {
        "timestamp": now_utc,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG:{json.dumps(log_entry)}")

def run_batch(correlation_id=None):
    start_time = time.time()
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    log_structured(
        step="start",
        outcome="success",
        correlation_id=correlation_id,
        outcome_detail="Batch parsing process initiated."
    )

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        msg = f"Input file not found: {input_file}"
        log_structured(
            step="input_check",
            outcome="error",
            correlation_id=correlation_id,
            outcome_detail=msg
        )
        print(f"[ERROR] {msg}")
        return BatchResult("NO_NEW_ITEMS", 0, len(load_ledger(ledger_path)))

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        msg = f"Could not load rules from {os.path.join(project_root, 'rules')}"
        log_structured(
            step="rule_loading",
            outcome="error",
            correlation_id=correlation_id,
            outcome_detail=f"{msg}: {e}"
        )
        raise RuleLoadError(msg) from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        msg = f"Failed to read input file: {input_file}"
        log_structured(
            step="input_reading",
            outcome="error",
            correlation_id=correlation_id,
            outcome_detail=f"{msg}: {e}"
        )
        raise InputReadError(msg) from e

    if not dna_list:
        msg = "No DNA strings found in toSequence.txt"
        log_structured(
            step="input_check",
            outcome="skipped",
            correlation_id=correlation_id,
            outcome_detail=msg
        )
        print(f"[WARN] {msg}")
        return BatchResult("NO_NEW_ITEMS", 0, len(load_ledger(ledger_path)))

    ledger = load_ledger(ledger_path)

    # Output file paths
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

        # Check if already processed
        if idempotency_key in ledger:
            terminal_outcome = ledger[idempotency_key].get('terminal_outcome')
            # Support flat/structured ledger
            if isinstance(terminal_outcome, dict):
                outcome_str = terminal_outcome.get('terminal_outcome', DNAStatus.SKIPPED)
            else:
                outcome_str = terminal_outcome or DNAStatus.SKIPPED

            log_structured(
                step="idempotency_check",
                outcome="skipped",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplication hit. Already processed with outcome: {outcome_str}"
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={outcome_str}")
            continue

        log_structured(
            step="idempotency_check",
            outcome="success",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            outcome_detail="Deduplication miss. Processing item."
        )
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

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['dna_sequence'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'dna_sequence': dna_str,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {
                'dna': dna_str,
                'dna_sequence': dna_str,
                'error': str(e)
            }
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

        # Save to ledger
        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        log_structured(
            step="process_item",
            outcome=outcome.value,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            outcome_detail=f"Item parsed. Status: {outcome.value}"
        )
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome.value}")
        new_processed_count += 1

    # Only rewrite files if new sequences were processed
    if new_processed_count > 0:
        # Save ledger atomically
        try:
            save_ledger(ledger_path, ledger)
        except Exception as e:
            msg = f"Failed to save ledger: {e}"
            log_structured(
                step="ledger_saving",
                outcome="error",
                correlation_id=correlation_id,
                outcome_detail=msg
            )
            raise

        # Write output files atomically
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
                msg = "Failed to write output files atomically"
                log_structured(
                    step="atomic_write",
                    outcome="error",
                    correlation_id=correlation_id,
                    outcome_detail=f"{msg}: {e}"
                )
                raise AtomicWriteError(msg) from e

    end_latency_ms = (time.time() - start_time) * 1000.0
    status_result = "SUCCESS" if new_processed_count > 0 else "NO_NEW_ITEMS"

    log_structured(
        step="end",
        outcome="success",
        correlation_id=correlation_id,
        latency_ms=end_latency_ms,
        outcome_detail=f"Batch parsing finished. Processed {new_processed_count} items. Status: {status_result}"
    )

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

    return BatchResult(
        status=status_result,
        processed_count=new_processed_count,
        total_ledger_items=len(ledger)
    )

main = run_batch
