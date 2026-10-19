#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys for Systemic Feedback
MSG_KEY_CONSEQUENCE = "Heat Accumulation"
MSG_KEY_REFUSAL_REASON = "Thermal Lockout"
MSG_KEY_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# Thermal Fatigue System Rules
MAX_CORE_HEAT = 10.0
HEAT_PER_SEQUENCE = 2.0
COOLING_RATE_PER_SEC = 0.5

class DNAStatus(str, Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal limits are exceeded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger fails due to file corruption."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic output file writing fails."""
    pass

def log_structured(correlation_id=None, actor_id="system", chain_name="dna_batch_parser",
                   step="process_batch", outcome="success", latency_ms=0,
                   idempotency_key=None, outcome_detail=None):
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_payload = {
        "timestamp": now_utc,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail or {}
    }
    print(f"JSON_LOG: {json.dumps(log_payload)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_path}") from e
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
                if not isinstance(content, dict):
                    raise LedgerLoadError(f"Ledger content must be a JSON object: {ledger_path}")
                if "ledger" in content:
                    return content
                else:
                    return {
                        "ledger": content,
                        "system_state": {
                            "core_heat": 0.0,
                            "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                        }
                    }
        except Exception as e:
            if isinstance(e, LedgerLoadError):
                raise
            raise LedgerLoadError(f"Corrupted ledger file: {ledger_path}") from e
    return {
        "ledger": {},
        "system_state": {
            "core_heat": 0.0,
            "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
    }

def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    # Output file paths defined unconditionally
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_list = read_input_file(input_file)
    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    full_ledger_data = load_ledger(ledger_path)
    ledger = full_ledger_data.get("ledger", {})
    system_state = full_ledger_data.get("system_state", {
        "core_heat": 0.0,
        "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    })

    # Thermal cooling calculation
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_utc_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    last_time_str = system_state.get("last_processed_timestamp", now_utc_str)

    try:
        last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
        elapsed_sec = max(0.0, (now_utc - last_time).total_seconds())
    except Exception:
        elapsed_sec = 0.0

    core_heat = float(system_state.get("core_heat", 0.0))
    core_heat = max(0.0, core_heat - elapsed_sec * COOLING_RATE_PER_SEC)

    # Load existing JSON output
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
        except Exception:
            parsed_json = []

    # Load existing CSV rows
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

    for dna_seq in dna_list:
        idempotency_key = dna_seq

        # Check idempotency
        if idempotency_key in ledger:
            existing_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={existing_outcome}")
            log_structured(
                correlation_id=correlation_id,
                step="idempotency_check",
                outcome=DNAStatus.SKIPPED.value,
                idempotency_key=idempotency_key,
                outcome_detail={"message": "Sequence already processed", "terminal_outcome": existing_outcome}
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Check Thermal Limit
        if core_heat + HEAT_PER_SEQUENCE > MAX_CORE_HEAT:
            print(f"[Thermal] core_heat={core_heat:.2f} + {HEAT_PER_SEQUENCE:.2f} > max={MAX_CORE_HEAT:.2f}. Lockout triggered!")
            system_state["core_heat"] = core_heat
            system_state["last_processed_timestamp"] = now_utc_str
            save_ledger(ledger_path, {"ledger": ledger, "system_state": system_state})

            log_structured(
                correlation_id=correlation_id,
                step="thermal_check",
                outcome=DNAStatus.REFUSED.value,
                idempotency_key=idempotency_key,
                outcome_detail={
                    "consequence": MSG_KEY_CONSEQUENCE,
                    "refusal_reason": MSG_KEY_REFUSAL_REASON,
                    "next_action_hint": MSG_KEY_NEXT_ACTION_HINT,
                    "core_heat": core_heat
                }
            )
            raise ThermalOverloadError(f"{MSG_KEY_REFUSAL_REASON}: Core heat capacity exceeded. {MSG_KEY_NEXT_ACTION_HINT}")

        # Accumulate heat
        core_heat += HEAT_PER_SEQUENCE

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

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    # Update system state thermal heat & timestamp
    system_state["core_heat"] = core_heat
    system_state["last_processed_timestamp"] = now_utc_str

    if new_processed_count > 0:
        # Save updated ledger
        save_ledger(ledger_path, {"ledger": ledger, "system_state": system_state})

        # Atomic write for JSON and CSV outputs
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
                raise PersistenceError("Failed to write output files atomically") from e

    latency_ms = int((time.time() - start_time) * 1000)
    log_structured(
        correlation_id=correlation_id,
        step="batch_complete",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=latency_ms,
        outcome_detail={"new_processed_count": new_processed_count, "core_heat": core_heat}
    )

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}. Core heat: {core_heat:.2f}")

# Expose main alias for backwards compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
