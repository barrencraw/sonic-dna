#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from datetime import datetime, timezone
from enum import Enum

from utils.dna_calculator import DNACalculator, RuleParseError

# UI message constants for thermal fatigue
MSG_HEAT_ACCUMULATION = "Heat Accumulation"
MSG_THERMAL_LOCKOUT = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

HEAT_PER_SEQUENCE = 2.0
LOCKOUT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5

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

class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence and writing failures."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger file fails due to corrupted JSON."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic temp file write/fsync/replace fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when core heat exceeds safety lockout threshold."""
    pass

def log_structured(event_type, correlation_id=None, actor_id="batch_parser", chain_name="dna_batch_parsing", step="start", outcome=DNAStatus.SUCCESS, latency_ms=0, idempotency_key=None, outcome_detail=""):
    now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    outcome_str = outcome.value if isinstance(outcome, DNAStatus) else str(outcome)
    log_entry = {
        "timestamp": now_utc,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome_str,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_sequence_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequence_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_path}") from e
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

def parse_utc_timestamp(ts_str):
    if not ts_str:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S'):
        try:
            dt = datetime.strptime(ts_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return None

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger_data):
    try:
        dir_name = os.path.dirname(ledger_path)
        ensure_folder(dir_name)
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
            json.dump(ledger_data, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name
        os.replace(temp_name, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())

    log_structured(
        "batch_start",
        correlation_id=correlation_id,
        actor_id=actor_id,
        step="start",
        outcome=DNAStatus.SUCCESS,
        latency_ms=0,
        outcome_detail="Started DNA batch parsing chain"
    )

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_structured(
            "batch_end",
            correlation_id=correlation_id,
            actor_id=actor_id,
            step="end",
            outcome=DNAStatus.ERROR,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)
    log_structured(
        "read_input",
        correlation_id=correlation_id,
        actor_id=actor_id,
        step="read_input",
        outcome=DNAStatus.SUCCESS,
        latency_ms=(time.time() - start_time) * 1000,
        outcome_detail=f"Read {len(dna_sequence_list)} DNA sequences"
    )

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        log_structured(
            "batch_end",
            correlation_id=correlation_id,
            actor_id=actor_id,
            step="end",
            outcome=DNAStatus.SUCCESS,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail="No DNA sequences found"
        )
        return

    raw_ledger_data = load_ledger(ledger_path)
    if "ledger" in raw_ledger_data and isinstance(raw_ledger_data["ledger"], dict):
        ledger = raw_ledger_data["ledger"]
        system_state = raw_ledger_data.get("system_state", {})
    else:
        ledger = raw_ledger_data
        system_state = {}

    core_heat = float(system_state.get("core_heat", 0.0))
    last_processed_ts = system_state.get("last_processed_timestamp")

    # Calculate thermal dissipation
    now_dt = datetime.now(timezone.utc)
    if last_processed_ts:
        last_dt = parse_utc_timestamp(last_processed_ts)
        if last_dt:
            elapsed_sec = (now_dt - last_dt).total_seconds()
            if elapsed_sec > 0:
                heat_dissipated = elapsed_sec * COOLING_RATE_PER_SEC
                core_heat = max(0.0, core_heat - heat_dissipated)

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
    refusal_error = None

    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger:
            existing_entry = ledger[idempotency_key]
            existing_outcome = existing_entry.get('terminal_outcome', '') if isinstance(existing_entry, dict) else ''
            if str(existing_outcome).lower() in ['success', 'error', 'skipped', 'refused']:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={existing_outcome}")
                log_structured(
                    "dedupe_check",
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    step="dedupe_check",
                    outcome=DNAStatus.SKIPPED,
                    latency_ms=(time.time() - start_time) * 1000,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Dedupe hit with terminal outcome {existing_outcome}"
                )
                continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if core_heat >= LOCKOUT_THRESHOLD:
            outcome = DNAStatus.REFUSED
            refusal_msg = f"{MSG_HEAT_ACCUMULATION}: {MSG_THERMAL_LOCKOUT}. {MSG_NEXT_ACTION_HINT}"
            ledger[idempotency_key] = {
                'terminal_outcome': outcome.value,
                'timestamp': now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            log_structured(
                "parse_sequence",
                correlation_id=correlation_id,
                actor_id=actor_id,
                step="parse_sequence",
                outcome=DNAStatus.REFUSED,
                latency_ms=(time.time() - start_time) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail=refusal_msg
            )
            refusal_error = ThermalOverloadError(refusal_msg)
            break

        try:
            result = calculator.parse(dna_seq)
            entry = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_seq
            flat['dna_sequence'] = dna_seq
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS
            outcome_detail = "Successfully parsed DNA sequence"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            }
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR
            outcome_detail = f"Parse error: {str(e)}"

        core_heat += HEAT_PER_SEQUENCE
        now_dt = datetime.now(timezone.utc)
        ts_now_str = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': ts_now_str
        }

        log_structured(
            "parse_sequence",
            correlation_id=correlation_id,
            actor_id=actor_id,
            step="parse_sequence",
            outcome=outcome,
            latency_ms=(time.time() - start_time) * 1000,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome.value}")
        new_processed_count += 1

    updated_ledger_data = {
        "ledger": ledger,
        "system_state": {
            "core_heat": core_heat,
            "last_processed_timestamp": now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
    }

    if new_processed_count > 0:
        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

                # 3) Atomic rename
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

                log_structured(
                    "atomic_write",
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    step="atomic_write",
                    outcome=DNAStatus.SUCCESS,
                    latency_ms=(time.time() - start_time) * 1000,
                    outcome_detail="Atomic write of output files succeeded"
                )
        except Exception as e:
            raise AtomicWriteError("Failed to write output files atomically") from e

        save_ledger(ledger_path, updated_ledger_data)
    elif refusal_error is not None:
        save_ledger(ledger_path, updated_ledger_data)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

    log_structured(
        "batch_end",
        correlation_id=correlation_id,
        actor_id=actor_id,
        step="end",
        outcome=DNAStatus.REFUSED if refusal_error else DNAStatus.SUCCESS,
        latency_ms=(time.time() - start_time) * 1000,
        outcome_detail=f"Batch execution complete. Processed {new_processed_count} new sequences."
    )

    if refusal_error is not None:
        raise refusal_error

main = run_batch

if __name__ == '__main__':
    main()
