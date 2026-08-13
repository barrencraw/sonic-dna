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

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when processing is refused due to mainframe thermal lockout."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when a ledger file exists but is corrupted."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
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
                content = json.load(f)
                if isinstance(content, dict):
                    if 'ledger' in content:
                        return content
                    else:
                        # Fallback for legacy flat layout
                        return {
                            'ledger': content,
                            'system_state': {
                                'core_heat': 0.0,
                                'last_processed_timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                            }
                        }
                else:
                    raise LedgerLoadError("Ledger is not a dictionary")
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Ledger JSON is corrupted: {e}") from e
        except Exception as e:
            raise LedgerLoadError(f"Failed to read ledger: {e}") from e
    return {
        'ledger': {},
        'system_state': {
            'core_heat': 0.0,
            'last_processed_timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
    }

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def log_structured(step, outcome, correlation_id=None, actor_id=None, chain_name="dna_batch_processing", latency_ms=0, idempotency_key=None, outcome_detail=None):
    # Emit structured UTC ISO 8601 logs prefixed with JSON_LOG:
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "system",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None):
    # Determine file paths
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

    # Load ledger
    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data.get('ledger', {})
    system_state = ledger_data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})

    # 1) Calculate thermal fatigue decay
    core_heat = system_state.get('core_heat', 0.0)
    last_processed_str = system_state.get('last_processed_timestamp')
    current_time = datetime.datetime.now(datetime.timezone.utc)

    if last_processed_str:
        try:
            last_time = datetime.datetime.strptime(last_processed_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (current_time - last_time).total_seconds())
            decay = elapsed_seconds * 0.5
            core_heat = max(0.0, core_heat - decay)
        except Exception:
            pass

    # 2) Load existing JSON output
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

    # 3) Load existing CSV rows
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

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
                log_structured(
                    step="sequence_deduplication",
                    outcome=DNAStatus.SKIPPED,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    outcome_detail="Skipped via ledger"
                )
                continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            # Check thermal lockout before processing new sequence
            if core_heat >= 10.0:
                log_structured(
                    step="thermal_lockout_check",
                    outcome=DNAStatus.REFUSED,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    outcome_detail="Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines."
                )
                raise ThermalOverloadError("Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines.")

            start_time_ms = int(time.time() * 1000)
            try:
                result = calculator.parse(dna_str)
                # To preserve complete backwards compatibility with legacy layout, we write both `dna` and `dna_sequence` keys
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
                # Add heat units
                core_heat += 2.0
                outcome_detail = "Heat Accumulation"

            except RuleParseError as e:
                parsed_json.append({
                    'dna': dna_str,
                    'dna_sequence': dna_str,
                    'error': str(e)
                })
                flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                outcome = DNAStatus.ERROR
                outcome_detail = f"Parse Error: {str(e)}"

            # Update entry in ledger
            ledger[idempotency_key] = {
                'terminal_outcome': outcome.value,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1

            end_time_ms = int(time.time() * 1000)
            log_structured(
                step="sequence_processing",
                outcome=outcome,
                correlation_id=correlation_id,
                latency_ms=(end_time_ms - start_time_ms),
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail
            )

    finally:
        # Save the updated ledger structure & thermal state regardless of success or raise
        # (This ensures 'no silent drains' and mathematical consistency of heat / thermal cooling cycle recording)
        updated_ledger_data = {
            'ledger': ledger,
            'system_state': {
                'core_heat': core_heat,
                'last_processed_timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
        }

        # Save ledger back to file
        try:
            save_ledger(ledger_path, updated_ledger_data)
        except Exception as e:
            raise LedgerSaveError(f"Failed to save ledger: {e}") from e

        # Rewrite output JSON and CSV only if new sequences were successfully processed
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

    print(f"[OK] Parsed {len(dna_list)} DNA strings.")
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

# Maintain backward compatibility alias
main = run_batch

if __name__ == '__main__':
    run_batch()
