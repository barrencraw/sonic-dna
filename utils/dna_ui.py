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

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when safety lockout threshold is exceeded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger atomically fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing JSON/CSV output atomically fails."""
    pass

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class BatchResult:
    def __init__(self, status, processed_count, total_ledger_items):
        self.status = status
        self.processed_count = processed_count
        self.total_ledger_items = total_ledger_items

def log_structured(step, outcome, latency_ms=0, correlation_id=None, actor_id="mainframe_core", chain_name="dna_batch_parser", idempotency_key=None, outcome_detail=None):
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_entry = {
        "timestamp": now_str,
        "correlation_id": correlation_id if correlation_id is not None else "N/A",
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key if idempotency_key is not None else "N/A",
        "outcome_detail": outcome_detail if outcome_detail is not None else "N/A"
    }
    print(f"JSON_LOG:{json.dumps(log_entry)}")

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
                if isinstance(data, dict):
                    if 'ledger' in data and 'system_state' in data:
                        return data['ledger']
                    else:
                        return data
        except Exception:
            return {}
    return {}

def load_ledger_structured(ledger_path):
    """
    Returns (ledger_dict, system_state)
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if 'ledger' in data and 'system_state' in data:
                        return data['ledger'], data['system_state']
                    else:
                        # Legacy flat layout
                        return data, {'core_heat': 0.0, 'last_processed_timestamp': None}
        except Exception:
            return {}, {'core_heat': 0.0, 'last_processed_timestamp': None}
    return {}, {'core_heat': 0.0, 'last_processed_timestamp': None}

def save_ledger(ledger_path, ledger, system_state=None):
    if system_state is None:
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}
    ledger_dir = os.path.dirname(ledger_path)
    ensure_folder(ledger_dir)
    temp_name = None
    try:
        data_to_save = {
            'ledger': ledger,
            'system_state': system_state
        }
        with tempfile.NamedTemporaryFile('w', dir=ledger_dir, delete=False, encoding='utf-8') as f:
            temp_name = f.name
            json.dump(data_to_save, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, ledger_path)
    except Exception as e:
        if temp_name and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except OSError:
                pass
        raise LedgerSaveError("Failed to save ledger atomically") from e

def run_batch(correlation_id=None):
    start_time_ms = int(time.time() * 1000)
    error_occurred = False

    # Define output file paths at the beginning to avoid UnboundLocalError
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    log_structured(
        step="batch_start",
        outcome="success",
        correlation_id=correlation_id,
        outcome_detail=f"Starting batch parser with input: {input_file}"
    )

    try:
        if not os.path.isfile(input_file):
            return BatchResult("NO_NEW_ITEMS", 0, 0)

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
            log_structured(
                step="batch_empty",
                outcome="success",
                correlation_id=correlation_id,
                outcome_detail="No DNA sequences found to process"
            )
            ledger, system_state = load_ledger_structured(ledger_path)
            return BatchResult("NO_NEW_ITEMS", 0, len(ledger))

        ledger, system_state = load_ledger_structured(ledger_path)

        # ─── Calculate heat dissipation (cooling) ───
        core_heat = system_state.get('core_heat', 0.0)
        last_time_str = system_state.get('last_processed_timestamp')

        current_time_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        current_time = datetime.datetime.strptime(current_time_str, '%Y-%m-%dT%H:%M:%SZ')

        if last_time_str:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ')
            elapsed_seconds = (current_time - last_time).total_seconds()
            if elapsed_seconds > 0:
                dissipated = elapsed_seconds * 0.5
                core_heat = max(0.0, core_heat - dissipated)

        # ─── Load existing JSON output ───
        parsed_json = []
        if os.path.exists(json_output_path):
            try:
                with open(json_output_path, 'r', encoding='utf-8') as jf:
                    parsed_json = json.load(jf)
                    if not isinstance(parsed_json, list):
                        parsed_json = []
            except Exception:
                parsed_json = []

        # ─── Load existing CSV rows ───
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
                log_structured(
                    step="deduplication",
                    outcome="success",
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Dedupe hit. Previous outcome: {ledger[idempotency_key]['terminal_outcome']}"
                )
                continue

            # Check core heat lockout safety threshold
            if core_heat >= 10.0:
                # Standardised UI message keys:
                # refusal reason: "Thermal Lockout"
                # next action hint: "Wait for dissipation. The system is indifferent to your deadlines."
                err_msg = "Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines."

                # Record in ledger with 'refused' outcome
                ledger[idempotency_key] = {
                    'terminal_outcome': DNAStatus.REFUSED,
                    'timestamp': current_time_str
                }
                system_state['core_heat'] = core_heat
                system_state['last_processed_timestamp'] = current_time_str

                # Save ledger with refusal before raising error (no silent drains)
                save_ledger(ledger_path, ledger, system_state)

                log_structured(
                    step="process_item",
                    outcome="error",
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    outcome_detail=err_msg
                )
                raise ThermalOverloadError(err_msg)

            log_structured(
                step="process_item",
                outcome="processing",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail="Processing new DNA sequence"
            )

            try:
                result = calculator.parse(dna_str)
                # Write both dna and dna_sequence keys to preserve backwards compatibility
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

                # Consequence applied: "Heat Accumulation" (adds 2.0 heat units)
                core_heat += 2.0

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_str,
                    'dna_sequence': dna_str,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': current_time_str
            }
            new_processed_count += 1

            log_structured(
                step="process_item_complete",
                outcome="success" if outcome == DNAStatus.SUCCESS else "error",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Parsed with outcome: {outcome}. Consequence: Heat Accumulation applied (+2.0 heat, current heat: {core_heat:.2f})"
            )

        # Update and save system state
        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = current_time_str

        # ATOMIC WRITE PATTERN:
        # Save ledger and write files atomically only if new_processed_count > 0
        if new_processed_count > 0:
            # 1. Write outputs atomically to temp dir first
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

                try:
                    # Write JSON
                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    # Write CSV
                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())

                    # Atomic replace
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

                except Exception as e:
                    raise AtomicWriteError("Failed to write output files atomically") from e

            # Save the ledger atomically
            save_ledger(ledger_path, ledger, system_state)

        else:
            # If no new items, we can still save updated core heat if it cooled down
            save_ledger(ledger_path, ledger, system_state)

        latency = int(time.time() * 1000) - start_time_ms
        status = "SUCCESS" if new_processed_count > 0 else "NO_NEW_ITEMS"

        log_structured(
            step="batch_complete",
            outcome="success",
            latency_ms=latency,
            correlation_id=correlation_id,
            outcome_detail=f"Batch parse complete. Status: {status}. Processed: {new_processed_count}, Ledger total: {len(ledger)}"
        )
        return BatchResult(status, new_processed_count, len(ledger))

    except Exception as e:
        error_occurred = True
        latency = int(time.time() * 1000) - start_time_ms
        log_structured(
            step="batch_failure",
            outcome="error",
            latency_ms=latency,
            correlation_id=correlation_id,
            outcome_detail=str(e)
        )
        raise e

    finally:
        latency = int(time.time() * 1000) - start_time_ms
        try:
            # Cleanup any files/directories if needed
            pass
        except Exception as cleanup_err:
            log_structured(
                step="cleanup_failure",
                outcome="error",
                latency_ms=latency,
                correlation_id=correlation_id,
                outcome_detail=str(cleanup_err)
            )
            if not error_occurred:
                raise cleanup_err

# Alias maintained for backwards compatibility
main = run_batch
