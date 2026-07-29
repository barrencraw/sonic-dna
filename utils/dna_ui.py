#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import datetime
import uuid
from enum import Enum
from dataclasses import dataclass
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

@dataclass
class DNAProcessingResult:
    status: DNAStatus
    dna_sequence: str
    rule_name: str = None
    parsed_values: dict = None
    error_message: str = None

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
    """Raised when writing or moving the ledger file fails."""
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

def get_utc_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    outcome_val = outcome.value if isinstance(outcome, Enum) else outcome
    log_data = {
        "timestamp": get_utc_timestamp(),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome_val,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
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
    ledger_dir = os.path.dirname(os.path.abspath(ledger_path))
    ensure_folder(ledger_dir)

    tmp_file = None
    try:
        # Create temp file in same directory
        fd, tmp_path = tempfile.mkstemp(dir=ledger_dir, prefix="ledger_tmp_", suffix=".json")
        tmp_file = tmp_path
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        # Cleanup partially written temporary file
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        raise LedgerSaveError("Failed to save ledger atomically") from e

def run_batch(correlation_id=None, actor_id="system"):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    start_time = time.time()
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_processing",
        step="batch_start",
        outcome=DNAStatus.SUCCESS,
        latency_ms=0,
        idempotency_key=None,
        outcome_detail="Starting batch parsing for DNA sequences."
    )

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_processing",
            step="batch_complete",
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
            chain_name="dna_batch_processing",
            step="batch_complete",
            outcome=DNAStatus.ERROR,
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail=f"Could not load rules: {e}"
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_processing",
            step="batch_complete",
            outcome=DNAStatus.ERROR,
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail=f"Failed to read input file: {e}"
        )
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_processing",
            step="batch_complete",
            outcome=DNAStatus.SUCCESS,
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key=None,
            outcome_detail="No DNA sequences found in toSequence.txt"
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
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_processing",
                step="process_sequence",
                outcome=DNAStatus.SKIPPED,
                latency_ms=0,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplication hit. Already processed with status: {ledger[idempotency_key]['terminal_outcome']}"
            )
            continue

        item_start = time.time()
        try:
            result = calculator.parse(dna_sequence)
            proc_result = DNAProcessingResult(
                status=DNAStatus.SUCCESS,
                dna_sequence=dna_sequence,
                rule_name=result['rule'],
                parsed_values=result['values']
            )
        except RuleParseError as e:
            proc_result = DNAProcessingResult(
                status=DNAStatus.ERROR,
                dna_sequence=dna_sequence,
                error_message=str(e)
            )

        latency_ms = int((time.time() - item_start) * 1000)

        # Process outcome
        if proc_result.status == DNAStatus.SUCCESS:
            entry = {
                'dna_sequence': proc_result.dna_sequence,
                'rule': proc_result.rule_name,
                'parsed': proc_result.parsed_values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(proc_result.rule_name, proc_result.parsed_values)
            flat['dna_sequence'] = proc_result.dna_sequence
            flat['rule'] = proc_result.rule_name
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS

        else:
            # On parse error, record as error entry
            parsed_json.append({
                'dna_sequence': proc_result.dna_sequence,
                'error': proc_result.error_message
            })
            # Also put a row in CSV listing error
            flat = {'dna_sequence': proc_result.dna_sequence, 'error': proc_result.error_message}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': get_utc_timestamp()
        }

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_processing",
            step="process_sequence",
            outcome=outcome,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
            outcome_detail=f"Sequence processed. Status: {outcome.value}"
        )
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)
    if new_processed_count > 0:
        try:
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

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
                # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

        except Exception as e:
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_processing",
                step="batch_complete",
                outcome=DNAStatus.ERROR,
                latency_ms=int((time.time() - start_time) * 1000),
                idempotency_key=None,
                outcome_detail=f"Persistence error: {e}"
            )
            raise PersistenceError("Failed to write output files atomically") from e

        # Save ledger
        save_ledger(ledger_path, ledger)

    total_latency_ms = int((time.time() - start_time) * 1000)
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_processing",
        step="batch_complete",
        outcome=DNAStatus.SUCCESS,
        latency_ms=total_latency_ms,
        idempotency_key=None,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

main = run_batch

if __name__ == '__main__':
    run_batch()
