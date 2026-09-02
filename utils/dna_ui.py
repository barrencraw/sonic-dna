#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
from datetime import datetime, timezone
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

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
    """Raised when reading input files fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence and I/O failures."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when reading or parsing the processed ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when mainframe core heat reaches or exceeds lockout threshold."""
    pass

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    timestamp_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_payload = {
        "timestamp": timestamp_iso,
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_payload)}")

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
        raise InputReadError(f"Failed to read input file {input_path}: {e}") from e
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
                data = json.load(f)
                if isinstance(data, dict):
                    if "ledger" in data and isinstance(data["ledger"], dict):
                        return data
                    # Convert legacy flat ledger to structured layout
                    return {
                        "ledger": data,
                        "system_state": {
                            "core_heat": 0.0,
                            "last_processed_timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                        }
                    }
                return {
                    "ledger": {},
                    "system_state": {
                        "core_heat": 0.0,
                        "last_processed_timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                    }
                }
        except Exception as e:
            raise LedgerLoadError(f"Failed to load or parse ledger file {ledger_path}: {e}") from e
    return {
        "ledger": {},
        "system_state": {
            "core_heat": 0.0,
            "last_processed_timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
    }

def save_ledger(ledger_path, ledger_data):
    try:
        dir_name = os.path.dirname(ledger_path) or '.'
        ensure_folder(dir_name)
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
            json.dump(ledger_data, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name
        os.replace(temp_name, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_parsing",
        step="start",
        outcome="success",
        latency_ms=0.0,
        idempotency_key="batch_start",
        outcome_detail="Initiating batch DNA sequence parsing"
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
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parsing",
            step="end",
            outcome="skipped",
            latency_ms=(time.time() - start_time) * 1000,
            idempotency_key="batch_end",
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

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parsing",
            step="end",
            outcome="skipped",
            latency_ms=(time.time() - start_time) * 1000,
            idempotency_key="batch_end",
            outcome_detail="No DNA sequences found in toSequence.txt"
        )
        return

    full_ledger_data = load_ledger(ledger_path)
    ledger = full_ledger_data.get("ledger", {})
    system_state = full_ledger_data.get("system_state", {
        "core_heat": 0.0,
        "last_processed_timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    })

    # Thermal dissipation calculation
    current_time_utc = datetime.now(timezone.utc)
    last_time_str = system_state.get("last_processed_timestamp")
    core_heat = float(system_state.get("core_heat", 0.0))

    if last_time_str:
        try:
            # Strip trailing Z if needed for strptime parsing
            cleaned_str = last_time_str.rstrip('Z')
            last_time = datetime.strptime(cleaned_str, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
            elapsed_seconds = (current_time_utc - last_time).total_seconds()
            if elapsed_seconds > 0:
                core_heat = max(0.0, core_heat - (elapsed_seconds * 0.5))
        except Exception:
            pass

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

    for dna_seq in dna_sequence_list:
        seq_start_time = time.time()
        idempotency_key = dna_seq

        # Check idempotency
        if idempotency_key in ledger:
            terminal_outcome = ledger[idempotency_key].get('terminal_outcome')
            if terminal_outcome in (DNAStatus.SUCCESS.value, DNAStatus.ERROR.value, DNAStatus.SKIPPED.value, DNAStatus.REFUSED.value):
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name="dna_batch_parsing",
                    step="parse",
                    outcome=DNAStatus.SKIPPED.value,
                    latency_ms=(time.time() - seq_start_time) * 1000,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Deduplicated hit for key {idempotency_key}"
                )
                continue

        # Check thermal fatigue lockout threshold
        if core_heat >= 10.0:
            system_state["core_heat"] = core_heat
            system_state["last_processed_timestamp"] = current_time_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
            full_ledger_data["system_state"] = system_state
            save_ledger(ledger_path, full_ledger_data)

            detail = (
                f"Thermal Lockout: Heat Accumulation. Core heat at {core_heat:.1f}. "
                f"Wait for dissipation. The system is indifferent to your deadlines."
            )
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parsing",
                step="thermal_check",
                outcome=DNAStatus.REFUSED.value,
                latency_ms=(time.time() - seq_start_time) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail=detail
            )
            raise ThermalOverloadError(detail)

        # Parse DNA sequence
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
            outcome = DNAStatus.SUCCESS.value
            outcome_detail = f"Successfully parsed sequence with rule {result['rule']}"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value
            outcome_detail = f"RuleParseError: {str(e)}"

        core_heat += 2.0
        now_utc = datetime.now(timezone.utc)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        system_state["core_heat"] = core_heat
        system_state["last_processed_timestamp"] = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parsing",
            step="parse",
            outcome=outcome,
            latency_ms=(time.time() - seq_start_time) * 1000,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )
        new_processed_count += 1

    # Atomic write pattern for JSON and CSV output files
    if new_processed_count > 0:
        full_ledger_data["ledger"] = ledger
        full_ledger_data["system_state"] = system_state
        save_ledger(ledger_path, full_ledger_data)

        write_start = time.time()
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            try:
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

            except Exception as e:
                raise AtomicWriteError("Failed to write output files atomically") from e

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parsing",
            step="atomic_write",
            outcome=DNAStatus.SUCCESS.value,
            latency_ms=(time.time() - write_start) * 1000,
            idempotency_key="batch_write",
            outcome_detail=f"Wrote {new_processed_count} new entries to JSON and CSV"
        )

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_parsing",
        step="end",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=(time.time() - start_time) * 1000,
        idempotency_key="batch_end",
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    run_batch()
