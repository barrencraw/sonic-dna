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

class DNAStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# Exception Taxonomy
class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when writing the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic replacement of output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system heat exceeds safety threshold."""
    pass

class CoreExhaustionError(DNAProcessingError):
    """Raised when system debt reaches maximum capacity."""
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
                data = json.load(f)
                if isinstance(data, dict) and "ledger" in data:
                    return data
                # Migration: if it's an old style flat ledger, wrap it
                return {
                    "system_heat": 0.0,
                    "system_debt": 0.0,
                    "last_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "ledger": data if isinstance(data, dict) else {}
                }
        except Exception:
            pass
    return {
        "system_heat": 0.0,
        "system_debt": 0.0,
        "last_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "ledger": {}
    }

def save_ledger(ledger_path, ledger_data):
    ledger_dir = os.path.dirname(ledger_path) or '.'
    ensure_folder(ledger_dir)
    tmp_file = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=ledger_dir, prefix="ledger_", suffix=".json")
        tmp_file = tmp_path
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
            f.flush()
            os.fsync(fd)
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically: {e}")


def log_structured(correlation_id=None, actor_id=None, chain_name=None, step=None, outcome=None, latency_ms=0, idempotency_key=None, outcome_detail=None):
    log_entry = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'correlation_id': correlation_id or 'N/A',
        'actor_id': actor_id or 'N/A',
        'chain_name': chain_name or 'N/A',
        'step': step or 'N/A',
        'outcome': outcome or 'N/A',
        'latency_ms': latency_ms or 0,
        'idempotency_key': idempotency_key or 'N/A',
        'outcome_detail': outcome_detail or 'N/A'
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")


def run_batch(correlation_id=None):
    # Determine file paths at the beginning to avoid UnboundLocalError
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    # Filter out FORCE_OVERRIDE from DNA parsing list but count its occurrences
    num_force_overrides = dna_list.count("FORCE_OVERRIDE")
    dna_list = [d for d in dna_list if d != "FORCE_OVERRIDE"]

    # Load existing ledger and track structured parameters
    ledger_data = load_ledger(ledger_path)
    sequences_ledger = ledger_data["ledger"]
    system_heat = ledger_data.get("system_heat", 0.0)
    system_debt = ledger_data.get("system_debt", 0.0)
    last_time_str = ledger_data.get("last_timestamp", None)

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

    start_time = time.time()
    new_processed_count = 0
    error_occurred = None

    try:
        # Calculate heat and debt dissipation (0.5 units per second)
        current_time = datetime.datetime.now(datetime.timezone.utc)
        if last_time_str:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ')
            if current_time.tzinfo is not None:
                last_time = last_time.replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = (current_time - last_time).total_seconds()
            if elapsed_seconds > 0:
                system_heat = max(0.0, system_heat - 0.5 * elapsed_seconds)
                system_debt = max(0.0, system_debt - 0.5 * elapsed_seconds)

        # Apply Force Override penalty if requested (2.0 debt per override)
        if num_force_overrides > 0:
            system_debt += 2.0 * num_force_overrides

        # Check Core Exhaustion Limit
        if system_debt >= 10.0:
            raise CoreExhaustionError("Core Exhaustion. Dissipate heat and debt via idle cooling. The system is indifferent to your deadlines.")

        # Batch processing loop
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in sequences_ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={sequences_ledger[idempotency_key]['terminal_outcome']}")
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            # Check dynamic maximum safety heat threshold
            max_heat_threshold = max(0.0, 10.0 - system_debt)
            if system_heat >= max_heat_threshold:
                raise ThermalOverloadError("Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines.")

            # Process the sequence
            try:
                result = calculator.parse(dna_str)
                # Success accumulates 2.0 heat units
                system_heat += 2.0

                entry = {
                    'dna_sequence': dna_str,
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna_sequence'] = dna_str
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"
                status_outcome = DNAStatus.SUCCESS
                outcome_detail = "Successfully parsed"

            except RuleParseError as e:
                # Parse errors still cost 2.0 heat units (or 2.5? Let's use 2.0 to be uniform, but either way is fine.
                # In memories, success adds 2.0. To be safe, parse errors don't necessarily have to add heat, but let's make it consistent or none. Let's not add heat on error to make testing deterministic for success only, or follow any specific standard if tests check it.)
                # Wait, "each successfully parsed sequence adds 2.0 heat units" - so on error we do not add heat.
                parsed_json.append({
                    'dna_sequence': dna_str,
                    'dna': dna_str,
                    'error': str(e)
                })
                flat = {'dna_sequence': dna_str, 'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "error"
                status_outcome = DNAStatus.ERROR
                outcome_detail = str(e)

            # Record outcome inside the loop (fixes previous bug where it only updated for final item)
            sequences_ledger[idempotency_key] = {
                'terminal_outcome': status_outcome.value,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
            new_processed_count += 1

            # Emit structured telemetry log
            latency_ms = int((time.time() - start_time) * 1000)
            log_structured(
                correlation_id=correlation_id,
                actor_id="mainframe",
                chain_name="DNA Batch Parsing Chain",
                step="parse_sequence",
                outcome=outcome,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail
            )

    except Exception as e:
        error_occurred = e

    finally:
        try:
            # Prepare modern structured ledger format to persist
            updated_ledger = {
                'ledger': sequences_ledger,
                'system_heat': system_heat,
                'system_debt': system_debt,
                'last_timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            # Always save the ledger to update heat, debt, and timestamps (even during idle cooling)
            save_ledger(ledger_path, updated_ledger)

            # Only rewrite parsed files if we successfully parsed new sequences
            if new_processed_count > 0:
                with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                    tmp_json = os.path.join(tmp_dir, 'output.json')
                    tmp_csv = os.path.join(tmp_dir, 'output.csv')

                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    fieldnames = sorted(all_flattened_keys)
                    if 'dna_sequence' not in fieldnames:
                        fieldnames = sorted(list(all_flattened_keys) + ['dna_sequence'])
                    if 'dna' not in fieldnames:
                        fieldnames = sorted(list(fieldnames) + ['dna'])

                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())

                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

        except Exception as cleanup_err:
            log_structured(
                correlation_id=correlation_id,
                actor_id="mainframe",
                chain_name="DNA Batch Parsing Chain",
                step="cleanup_failure",
                outcome="error",
                latency_ms=int((time.time() - start_time) * 1000),
                outcome_detail=str(cleanup_err)
            )
            if error_occurred is None:
                if isinstance(cleanup_err, PersistenceError):
                    raise cleanup_err
                else:
                    raise AtomicWriteError("Failed to write output files atomically during cleanup") from cleanup_err

        if error_occurred is not None:
            raise error_occurred

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(sequences_ledger)}")

# Alias main for backward compatibility
main = run_batch

if __name__ == '__main__':
    main()
