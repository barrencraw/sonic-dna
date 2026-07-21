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

# Thermal Fatigue Parameters
MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0

# Standardized UI Message Keys for Systemic Feedback
UI_MESSAGES = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

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
    """Raised when sequence parsing exceeds hardware heat limits."""
    pass

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    """
    Standardized telemetry logging utility emitting JSON logs with JSON_LOG: prefix.
    """
    # Use timezone-aware UTC datetime for timestamping
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "system",
        "chain_name": chain_name or "dna_batch_parsing",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
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
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def process_single_dna(dna_sequence, calculator, ledger_dict, current_heat):
    """
    Encapsulates DNA string parsing to classify outcomes into explicit DNAStatus enum values.
    """
    # 1. Idempotency logic: Skip if already exists in the ledger with a terminal outcome (success or error)
    if dna_sequence in ledger_dict:
        term_outcome = ledger_dict[dna_sequence].get('terminal_outcome')
        if term_outcome in [DNAStatus.SUCCESS, DNAStatus.ERROR]:
            return DNAStatus.SKIPPED, None, None

    # 2. Thermal fatigue limits: Refuse and Lockout if we exceed maximum allowed heat
    if current_heat + HEAT_PER_SEQ > MAX_HEAT:
        return DNAStatus.REFUSED, None, ThermalOverloadError("Thermal Lockout")

    # 3. Parse sequence
    try:
        result = calculator.parse(dna_sequence)
        return DNAStatus.SUCCESS, result, None
    except RuleParseError as e:
        return DNAStatus.ERROR, None, e

def run_batch(correlation_id=None):
    if correlation_id is None:
        import uuid
        correlation_id = str(uuid.uuid4())

    # Define working folders and paths
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

    # Read DNA strings (naming alignment: dna_sequence_list)
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)
    ledger_dict = ledger.get('ledger', {})

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

    # Thermal dissipation calculation
    last_heat = ledger.get('system_heat', 0.0)
    last_time_str = ledger.get('last_processed_time', None)
    current_heat = last_heat
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    elapsed_seconds = 0.0

    if last_time_str:
        try:
            last_time = datetime.datetime.fromisoformat(last_time_str.replace('Z', '+00:00'))
            elapsed_seconds = (now_utc - last_time).total_seconds()
            dissipation = elapsed_seconds * COOLING_RATE
            current_heat = max(0.0, last_heat - dissipation)
        except Exception as e:
            current_heat = last_heat

    # Log initial fatigue and dissipation state
    log_structured(
        correlation_id=correlation_id,
        actor_id="system",
        chain_name="dna_batch_parsing",
        step="thermal_dissipation",
        outcome="success",
        latency_ms=0,
        idempotency_key="N/A",
        outcome_detail=f"Initial heat: {last_heat:.2f}, Dissipated to: {current_heat:.2f} over {elapsed_seconds:.2f}s"
    )

    new_processed_count = 0
    error_occurred = None

    try:
        # Batch processing loop with naming alignment: dna_sequence
        for dna_sequence in dna_sequence_list:
            status, result, err = process_single_dna(dna_sequence, calculator, ledger_dict, current_heat)

            if status == DNAStatus.SKIPPED:
                log_structured(
                    correlation_id=correlation_id,
                    actor_id="system",
                    chain_name="dna_batch_parsing",
                    step="idempotency_check",
                    outcome="skipped",
                    latency_ms=0,
                    idempotency_key=dna_sequence,
                    outcome_detail="Sequence already processed"
                )
                continue

            elif status == DNAStatus.REFUSED:
                log_structured(
                    correlation_id=correlation_id,
                    actor_id="system",
                    chain_name="dna_batch_parsing",
                    step="thermal_check",
                    outcome="refused",
                    latency_ms=0,
                    idempotency_key=dna_sequence,
                    outcome_detail="Thermal Lockout"
                )
                raise err

            elif status == DNAStatus.SUCCESS:
                # Accumulate consequence: heat accumulation
                current_heat += HEAT_PER_SEQ
                entry = {
                    'dna': dna_sequence,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_sequence
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                ledger_dict[dna_sequence] = {
                    'terminal_outcome': DNAStatus.SUCCESS,
                    'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                }
                new_processed_count += 1

                log_structured(
                    correlation_id=correlation_id,
                    actor_id="system",
                    chain_name="dna_batch_parsing",
                    step="parse_sequence",
                    outcome="success",
                    latency_ms=1,
                    idempotency_key=dna_sequence,
                    outcome_detail="Successfully parsed DNA sequence"
                )

            elif status == DNAStatus.ERROR:
                # Bad samples still cause fatigue and heat
                current_heat += HEAT_PER_SEQ
                parsed_json.append({
                    'dna': dna_sequence,
                    'error': str(err)
                })
                # Put a row in CSV listing error
                flat = {'dna': dna_sequence, 'error': str(err)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())

                ledger_dict[dna_sequence] = {
                    'terminal_outcome': DNAStatus.ERROR,
                    'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                }
                new_processed_count += 1

                log_structured(
                    correlation_id=correlation_id,
                    actor_id="system",
                    chain_name="dna_batch_parsing",
                    step="parse_sequence",
                    outcome="error",
                    latency_ms=1,
                    idempotency_key=dna_sequence,
                    outcome_detail=str(err)
                )

    except Exception as e:
        error_occurred = e
        raise

    finally:
        # Atomic Write Pattern with explicit error_occurred checking
        try:
            # We persist system heat and updated timestamp to the ledger even if zero sequences processed
            ledger['system_heat'] = current_heat
            ledger['last_processed_time'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            ledger['ledger'] = ledger_dict

            save_ledger(ledger_path, ledger)

            # JSON and CSV output files are rewritten only if new_processed_count > 0
            if new_processed_count > 0:
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
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

                print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger_dict)}")
                print(f"     JSON → {json_output_path}")
                print(f"     CSV  → {csv_output_path}")

        except Exception as pe:
            # Raise PersistenceError only if no previous processing error occurred, to avoid masking
            if error_occurred is None:
                raise PersistenceError("Failed to write output files atomically") from pe
            else:
                # Suppress / log the cleanup error, do not raise so original is propagated
                print(f"[Cleanup] Suppressed persistence error since processing failed: {pe}")

main = run_batch

if __name__ == '__main__':
    main()
