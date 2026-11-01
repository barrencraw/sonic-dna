#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

UI_MESSAGES = {
    "CONSEQUENCE_APPLIED": "Heat Accumulation",
    "REFUSAL_REASON": "Thermal Lockout",
    "NEXT_ACTION_HINT": "Wait for dissipation. The system is indifferent to your deadlines."
}

HEAT_PER_SEQUENCE = 2.0
LOCKOUT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5

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
    """Raised when writing output or ledger fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger fails or is corrupted."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file persistence fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when core thermal heat reaches lockout threshold."""
    pass

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_data = {
        "timestamp": now_iso,
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
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

import tempfile

def load_ledger(ledger_path):
    """
    Loads ledger dictionary and system state from ledger_path.
    Returns dict formatted as {'ledger': {...}, 'system_state': {'core_heat': float, 'last_processed_timestamp': str}}.
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "ledger" in data and "system_state" in data:
                        return data
                    else:
                        # Legacy flat ledger format
                        return {
                            "ledger": data,
                            "system_state": {
                                "core_heat": 0.0,
                                "last_processed_timestamp": None
                            }
                        }
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}: {e}") from e
    return {
        "ledger": {},
        "system_state": {
            "core_heat": 0.0,
            "last_processed_timestamp": None
        }
    }

def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    start_time = time.time()
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

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

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    full_ledger_data = load_ledger(ledger_path)
    ledger = full_ledger_data.get("ledger", {})
    system_state = full_ledger_data.get("system_state", {"core_heat": 0.0, "last_processed_timestamp": None})

    core_heat = float(system_state.get("core_heat", 0.0))
    last_time_str = system_state.get("last_processed_timestamp")

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed = (now_dt - last_time).total_seconds()
            if elapsed > 0:
                core_heat = max(0.0, core_heat - elapsed * COOLING_RATE_PER_SEC)
        except Exception:
            pass

    # 1) Load existing JSON output
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
    initial_ledger = dict(ledger)

    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        seq_start = time.time()

        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="idempotency_check",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=int((time.time() - seq_start) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail={"dedupe_hit": True, "terminal_outcome": term_outcome}
            )
            continue

        if core_heat >= LOCKOUT_THRESHOLD:
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="thermal_check",
                outcome=DNAStatus.REFUSED.value,
                latency_ms=int((time.time() - seq_start) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail={
                    "consequence": UI_MESSAGES["CONSEQUENCE_APPLIED"],
                    "reason": UI_MESSAGES["REFUSAL_REASON"],
                    "core_heat": core_heat,
                    "hint": UI_MESSAGES["NEXT_ACTION_HINT"]
                }
            )
            # Update system state before raising
            full_ledger_data["system_state"]["core_heat"] = core_heat
            full_ledger_data["system_state"]["last_processed_timestamp"] = now_str
            save_ledger(ledger_path, full_ledger_data)
            raise ThermalOverloadError(
                f"{UI_MESSAGES['REFUSAL_REASON']}: Core heat {core_heat:.1f} >= {LOCKOUT_THRESHOLD}. "
                f"{UI_MESSAGES['NEXT_ACTION_HINT']}"
            )

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value
            core_heat += HEAT_PER_SEQUENCE

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        seq_latency = int((time.time() - seq_start) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parser",
            step="parse_sequence",
            outcome=outcome,
            latency_ms=seq_latency,
            idempotency_key=idempotency_key,
            outcome_detail={"core_heat": core_heat, "consequence": UI_MESSAGES["CONSEQUENCE_APPLIED"]}
        )

    # Save system state
    full_ledger_data["ledger"] = ledger
    full_ledger_data["system_state"]["core_heat"] = core_heat
    full_ledger_data["system_state"]["last_processed_timestamp"] = now_str

    if new_processed_count > 0:
        save_ledger(ledger_path, full_ledger_data)

        # Atomic write for JSON and CSV output
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
                raise AtomicWriteError(f"Failed to write output files atomically: {e}") from e

    total_latency = int((time.time() - start_time) * 1000)
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_parser",
        step="batch_complete",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=total_latency,
        idempotency_key="batch",
        outcome_detail={"processed_count": new_processed_count, "core_heat": core_heat}
    )

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    run_batch()
