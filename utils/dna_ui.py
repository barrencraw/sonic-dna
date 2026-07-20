#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Exceptions ---
class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal limits are exceeded."""
    pass

# --- Status Enum ---
class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# --- Parameters ---
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0

# --- Telemetry Logger ---
def log_structured(correlation_id, step, outcome, latency_ms=0, idempotency_key=None, outcome_detail=None, actor_id="system", chain_name="dna_batch_parser"):
    log_data = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'correlation_id': correlation_id,
        'actor_id': actor_id,
        'chain_name': chain_name,
        'step': step,
        'outcome': outcome,
        'latency_ms': round(latency_ms, 2),
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

# --- Helpers ---
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
                    return data
        except Exception:
            pass
    return {}

def save_ledger(ledger_path, ledger_data):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger_data, f, indent=2)

def process_single_dna(dna_str, calculator):
    """
    Parses a single DNA sequence and classifies outcome into a DNAStatus.
    Returns (DNAStatus, parsed_result_or_error_msg).
    """
    try:
        result = calculator.parse(dna_str)
        return DNAStatus.SUCCESS, result
    except RuleParseError as e:
        return DNAStatus.ERROR, str(e)
    except Exception as e:
        return DNAStatus.ERROR, str(e)

# --- Core Batch Processing Entrypoint ---
def run_batch(correlation_id=None):
    if correlation_id is None:
        import uuid
        correlation_id = str(uuid.uuid4())

    start_time = time.time()

    # Define output file paths once at the beginning
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            step="process_start",
            outcome="error",
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    log_structured(
        correlation_id=correlation_id,
        step="process_start",
        outcome="success",
        outcome_detail="Batch processing started"
    )

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        err_msg = f"Could not load rules from {os.path.join(project_root, 'rules')}: {e}"
        log_structured(
            correlation_id=correlation_id,
            step="load_rules",
            outcome="error",
            outcome_detail=err_msg
        )
        raise RuleLoadError(err_msg) from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        err_msg = f"Failed to read input file {input_file}: {e}"
        log_structured(
            correlation_id=correlation_id,
            step="read_input",
            outcome="error",
            outcome_detail=err_msg
        )
        raise DNAProcessingError(err_msg) from e

    if not dna_list:
        log_structured(
            correlation_id=correlation_id,
            step="process_end",
            outcome="success",
            outcome_detail="No DNA strings to process"
        )
        # We fall through to process cooling and save ledger anyway

    # Load ledger
    ledger_data = load_ledger(ledger_path)
    system_heat = ledger_data.get('system_heat', 0.0)
    last_processed_time = ledger_data.get('last_processed_time', None)
    ledger = ledger_data.get('ledger', {})

    # Check for flat legacy format
    if 'ledger' not in ledger_data and ledger_data:
        ledger = {k: v for k, v in ledger_data.items() if k not in ('system_heat', 'last_processed_time', 'ledger')}

    now = datetime.datetime.now(datetime.timezone.utc)
    now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Calculate thermal cooling
    if last_processed_time:
        try:
            last_time = datetime.datetime.fromisoformat(last_processed_time.replace('Z', '+00:00'))
            elapsed = (now - last_time).total_seconds()
            system_heat = max(0.0, system_heat - elapsed * COOLING_RATE)
        except Exception:
            pass

    # Load existing output files if they exist
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
        except Exception:
            parsed_json = []

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
    error_occurred = None

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str

            # Check idempotency
            if idempotency_key in ledger:
                term_outcome = ledger[idempotency_key].get('terminal_outcome')
                if term_outcome in (DNAStatus.SUCCESS.value, DNAStatus.ERROR.value):
                    log_structured(
                        correlation_id=correlation_id,
                        step="process_sequence",
                        outcome="skipped",
                        idempotency_key=idempotency_key,
                        outcome_detail=f"Deduplicated key: {idempotency_key}. Previous outcome: {term_outcome}"
                    )
                    continue

            # Check thermal lockout
            if system_heat + HEAT_PER_SEQ > MAX_HEAT:
                # Transition sequence to REFUSED state in ledger
                ledger[idempotency_key] = {
                    'terminal_outcome': DNAStatus.REFUSED.value,
                    'timestamp': now_str
                }

                msg_lockout = "Thermal Lockout"
                msg_consequence = "Heat Accumulation"
                msg_hint = "Wait for dissipation. The system is indifferent to your deadlines."
                err_detail = f"{msg_lockout}. {msg_consequence}. {msg_hint}"

                log_structured(
                    correlation_id=correlation_id,
                    step="refuse_sequence",
                    outcome="refused",
                    idempotency_key=idempotency_key,
                    outcome_detail=err_detail
                )
                raise ThermalOverloadError(err_detail)

            # Apply heat accumulation
            system_heat += HEAT_PER_SEQ

            seq_start = time.time()
            status, result = process_single_dna(dna_str, calculator)
            latency_ms = (time.time() - seq_start) * 1000.0

            if status == DNAStatus.SUCCESS:
                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                log_structured(
                    correlation_id=correlation_id,
                    step="process_sequence",
                    outcome="success",
                    latency_ms=latency_ms,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Successfully parsed DNA: {dna_str}"
                )
            else:
                error_msg = result
                parsed_json.append({
                    'dna': dna_str,
                    'error': error_msg
                })

                flat = {'dna': dna_str, 'error': error_msg}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                log_structured(
                    correlation_id=correlation_id,
                    step="process_sequence",
                    outcome="error",
                    latency_ms=latency_ms,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Failed to parse DNA: {dna_str}. Error: {error_msg}"
                )

            ledger[idempotency_key] = {
                'terminal_outcome': status.value,
                'timestamp': now_str
            }
            new_processed_count += 1

    except Exception as e:
        error_occurred = e
        raise

    finally:
        # Commit updated heat, timestamp, and processed/refused sequence ledger
        ledger_data['system_heat'] = system_heat
        ledger_data['last_processed_time'] = now_str
        ledger_data['ledger'] = ledger

        try:
            save_ledger(ledger_path, ledger_data)

            if new_processed_count > 0:
                with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                    tmp_json = os.path.join(tmp_dir, 'output.json')
                    tmp_csv = os.path.join(tmp_dir, 'output.csv')

                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    fieldnames = sorted(all_flattened_keys)
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

        except Exception as pe:
            if error_occurred is None:
                raise PersistenceError("Failed to write output files atomically") from pe
            print(f"[ERROR] Failed to save outputs during cleanup: {pe}")

    total_latency_ms = (time.time() - start_time) * 1000.0
    log_structured(
        correlation_id=correlation_id,
        step="process_end",
        outcome="success" if error_occurred is None else "error",
        latency_ms=total_latency_ms,
        outcome_detail=f"Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}"
    )

# Backward Compatibility Alias
main = run_batch

if __name__ == '__main__':
    main()
