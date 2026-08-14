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

class DNAStatus(str, Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input file cannot be read."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when ledger loading fails due to corruption or other issues."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when ledger saving fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic output writing fails."""
    pass

def log_structured(step, outcome, correlation_id=None, actor_id="mainframe", chain_name="dna_batch_parse", latency_ms=0.0, idempotency_key=None, outcome_detail=None):
    """
    Emits structured telemetry JSON logs prefixed with JSON_LOG:
    """
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
        "correlation_id": correlation_id or "default-corr-id",
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
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
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Ledger file corrupted at {ledger_path}") from e
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger: {str(e)}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger: {str(e)}") from e

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = f"corr-{int(time.time())}"

    log_structured(
        step="initiate_batch",
        outcome=DNAStatus.SUCCESS,
        correlation_id=correlation_id,
        idempotency_key=None,
        outcome_detail="Starting batch parsing of DNA sequences."
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
            step="check_input_file",
            outcome=DNAStatus.ERROR,
            correlation_id=correlation_id,
            outcome_detail=msg
        )
        print(f"[ERROR] {msg}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        msg = f"Could not load rules from {os.path.join(project_root, 'rules')}"
        log_structured(
            step="load_rules",
            outcome=DNAStatus.ERROR,
            correlation_id=correlation_id,
            outcome_detail=f"{msg}: {str(e)}"
        )
        raise RuleLoadError(msg) from e

    # Read DNA sequences
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        msg = f"Failed to read input file: {input_file}"
        log_structured(
            step="read_input",
            outcome=DNAStatus.ERROR,
            correlation_id=correlation_id,
            outcome_detail=f"{msg}: {str(e)}"
        )
        raise InputReadError(msg) from e

    if not dna_sequence_list:
        msg = "No DNA sequences found in toSequence.txt"
        log_structured(
            step="read_input",
            outcome=DNAStatus.SKIPPED,
            correlation_id=correlation_id,
            outcome_detail=msg
        )
        print(f"[WARN] {msg}")
        return

    ledger_data = load_ledger(ledger_path)
    if 'ledger' in ledger_data:
        ledger = ledger_data['ledger']
        is_structured = True
    else:
        ledger = ledger_data
        is_structured = False

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
                step="idempotency_check",
                outcome=DNAStatus.SKIPPED,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail="Deduplication hit. Sequence already processed.",
                latency_ms=0.0
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        start_time = time.perf_counter()
        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS
            outcome_detail = f"Successfully parsed rule {result['rule']}"

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            }
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR
            outcome_detail = str(e)

        latency_ms = (time.perf_counter() - start_time) * 1000

        # UPDATE THE LEDGER INSIDE THE LOOP
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_structured(
            step="process_sequence",
            outcome=outcome,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail,
            latency_ms=latency_ms
        )
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # Atomic write of output and ledger only if new_processed_count > 0
    if new_processed_count > 0:
        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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
                # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                log_structured(
                    step="atomic_write",
                    outcome=DNAStatus.ERROR,
                    correlation_id=correlation_id,
                    outcome_detail=f"Atomic write failed: {str(e)}"
                )
                raise AtomicWriteError("Failed to write output files atomically") from e

        # Save ledger
        # If we had structured layout, save structured. Else save flat.
        if is_structured:
            ledger_data['ledger'] = ledger
            save_ledger(ledger_path, ledger_data)
        else:
            save_ledger(ledger_path, ledger)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    if new_processed_count > 0:
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

    log_structured(
        step="complete_batch",
        outcome=DNAStatus.SUCCESS,
        correlation_id=correlation_id,
        outcome_detail=f"Processed {new_processed_count} new sequences."
    )

# Alias run_batch as main for backwards compatibility
main = run_batch
