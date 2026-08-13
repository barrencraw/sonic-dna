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
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# UI feedback message keys
UI_FEEDBACK = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

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
    """Raised when safety heat threshold of the mainframe is exceeded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input DNA sequences cannot be read."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when ledger exists but is corrupted."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    """
    Emits structured telemetry JSON logs prefixed with JSON_LOG:.
    Mandatory fields: timestamp, correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail.
    """
    # Use the local module namespace for datetime to allow deterministic mocking
    now_utc = datetime.datetime.utcnow()
    timestamp = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id if correlation_id is not None else "N/A",
        "actor_id": actor_id if actor_id is not None else "mainframe_core",
        "chain_name": chain_name if chain_name is not None else "dna_batch_parsing",
        "step": step,
        "outcome": str(outcome),
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key if idempotency_key is not None else "N/A",
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")

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
        except Exception as e:
            raise LedgerLoadError(f"Ledger file exists but is corrupted: {e}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError("Failed to save ledger") from e

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

    # Read DNA sequences
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger_data = load_ledger(ledger_path)

    # Standardize structured vs legacy flat layout
    if "ledger" in ledger_data and "system_state" in ledger_data:
        ledger = ledger_data["ledger"]
        system_state = ledger_data["system_state"]
    else:
        ledger = ledger_data
        system_state = {
            "core_heat": 0.0,
            "last_processed_timestamp": datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        }

    # Extract core heat and calculate decay
    core_heat = float(system_state.get("core_heat", 0.0))
    last_time_str = system_state.get("last_processed_timestamp")

    now_utc = datetime.datetime.utcnow()
    now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ')
            elapsed_seconds = (now_utc - last_time).total_seconds()
            if elapsed_seconds < 0:
                elapsed_seconds = 0.0
        except Exception:
            elapsed_seconds = 0.0
    else:
        elapsed_seconds = 0.0

    decay = elapsed_seconds * 0.5
    new_heat = max(0.0, core_heat - decay)

    if core_heat > 0.0 or elapsed_seconds > 0:
        log_structured(
            correlation_id=correlation_id,
            actor_id="mainframe_core",
            chain_name="dna_batch_parsing",
            step="cooldown",
            outcome="success",
            latency_ms=int(elapsed_seconds * 1000),
            idempotency_key=None,
            outcome_detail=f"Core heat dissipated from {core_heat:.2f} to {new_heat:.2f} over {elapsed_seconds:.2f} seconds."
        )

    core_heat = new_heat

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
    thermal_error_to_raise = None

    try:
        for dna_str in dna_sequence_list:
            idempotency_key = dna_str
            if idempotency_key in ledger:
                saved_entry = ledger[idempotency_key]
                terminal_outcome = saved_entry.get('terminal_outcome', '').lower()
                if terminal_outcome in ['success', 'error']:
                    print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
                    log_structured(
                        correlation_id=correlation_id,
                        actor_id="mainframe_core",
                        chain_name="dna_batch_parsing",
                        step="parse_sequence",
                        outcome="skipped",
                        latency_ms=0,
                        idempotency_key=idempotency_key,
                        outcome_detail=f"Deduplicated sequence. Saved outcome was {terminal_outcome}."
                    )
                    continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
            start_time = time.perf_counter()

            if core_heat >= 10.0:
                # This sequence is refused due to Thermal Lockout
                outcome = "refused"
                ledger[idempotency_key] = {
                    'terminal_outcome': outcome,
                    'dna': dna_str,
                    'dna_sequence': dna_str,
                    'timestamp': now_str
                }
                log_structured(
                    correlation_id=correlation_id,
                    actor_id="mainframe_core",
                    chain_name="dna_batch_parsing",
                    step="lockout",
                    outcome="refused",
                    latency_ms=0,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Refused sequence: {UI_FEEDBACK['refusal_reason']}. {UI_FEEDBACK['next_action_hint']}"
                )
                thermal_error_to_raise = ThermalOverloadError(f"{UI_FEEDBACK['refusal_reason']}: {UI_FEEDBACK['next_action_hint']}")
                break

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

                # Success adds 2.0 heat units
                outcome = "success"
                core_heat += 2.0
                outcome_detail = f"Successfully parsed sequence. Core heat increased to {core_heat:.2f}."
                print(f"[Feedback] Consequence applied: {UI_FEEDBACK['consequence_applied']}. Current heat: {core_heat:.2f}")

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
                outcome = "error"
                outcome_detail = str(e)

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'dna': dna_str,
                'dna_sequence': dna_str,
                'timestamp': now_str
            }

            log_structured(
                correlation_id=correlation_id,
                actor_id="mainframe_core",
                chain_name="dna_batch_parsing",
                step="parse_sequence",
                outcome=outcome,
                latency_ms=int((time.perf_counter() - start_time) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
            new_processed_count += 1

    finally:
        # Always update system state
        system_state["core_heat"] = core_heat
        system_state["last_processed_timestamp"] = now_str

        # Save ledger structured format
        structured_ledger = {
            "ledger": ledger,
            "system_state": system_state
        }
        save_ledger(ledger_path, structured_ledger)

    if new_processed_count > 0:
        try:
            # ATOMIC WRITE PATTERN:
            # 1. Write to a temporary directory in the same filesystem as the output folder
            # 2. Flush and sync files to ensure they are on disk
            # 3. Rename them to their final destination (atomic on most OSes)
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
            raise AtomicWriteError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    if new_processed_count > 0:
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

    # Re-raise thermal overload error if triggered
    if thermal_error_to_raise:
        raise thermal_error_to_raise

main = run_batch

if __name__ == '__main__':
    main()
