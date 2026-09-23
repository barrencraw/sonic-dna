#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import datetime
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys (Fatigue Pressure Axis)
UI_MESSAGES = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

# DNA Status Enum
class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# Exception Taxonomy
class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input file cannot be read."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal core heat limit is reached."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic write operation fails."""
    pass


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
                    if "ledger" in data and "system_state" in data:
                        return data
                    else:
                        # Legacy flat ledger fallback
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
        ensure_folder(os.path.dirname(ledger_path) or '.')
        with tempfile.TemporaryDirectory(dir=os.path.dirname(ledger_path) or '.') as tmp_dir:
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            with open(tmp_ledger, 'w', encoding='utf-8') as f:
                json.dump(ledger_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_ledger, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e

def write_outputs_atomically(output_folder, json_output_path, csv_output_path, parsed_json, csv_rows, all_flattened_keys):
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

def log_structured(timestamp, correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    outcome_str = outcome.value if isinstance(outcome, Enum) else str(outcome)
    log_data = {
        "timestamp": timestamp,
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome_str,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None, actor_id="batch_parser"):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

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

    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data.get("ledger", ledger_data)
    system_state = ledger_data.get("system_state", {"core_heat": 0.0, "last_processed_timestamp": None})

    core_heat = float(system_state.get("core_heat", 0.0))
    last_processed_timestamp = system_state.get("last_processed_timestamp")

    # Time & Thermal Dissipation
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_processed_timestamp:
        try:
            ts_str = last_processed_timestamp.replace('Z', '+00:00')
            last_dt = datetime.datetime.fromisoformat(ts_str)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = max(0.0, (now_dt - last_dt).total_seconds())
            heat_dissipated = elapsed_sec * 0.5
            core_heat = max(0.0, core_heat - heat_dissipated)
        except Exception:
            pass

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
    overload_occurred = False
    overload_error_msg = ""

    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED)
            log_structured(
                timestamp=now_iso,
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="deduplication_check",
                outcome=DNAStatus.SKIPPED,
                latency_ms=0,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit. Previous outcome: {term_outcome}"
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            continue

        # Check for thermal lockout before attempting parse
        if core_heat >= 10.0:
            overload_occurred = True
            overload_error_msg = f"{UI_MESSAGES['refusal_reason']}: Core heat ({core_heat:.1f}) reached safety limit (>= 10.0). {UI_MESSAGES['next_action_hint']}"
            log_structured(
                timestamp=now_iso,
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="thermal_check",
                outcome=DNAStatus.REFUSED,
                latency_ms=0,
                idempotency_key=idempotency_key,
                outcome_detail=overload_error_msg
            )
            print(f"[{UI_MESSAGES['consequence_applied']}] Refusing sequence {idempotency_key}. {overload_error_msg}")
            break

        start_time = time.time()
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
            entry = {
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            }
            parsed_json.append(entry)

            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR
            outcome_detail = f"Parse error: {str(e)}"

        latency_ms = int((time.time() - start_time) * 1000)
        core_heat += 2.0
        new_processed_count += 1

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value if isinstance(outcome, Enum) else str(outcome),
            'timestamp': now_iso
        }

        log_structured(
            timestamp=now_iso,
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parser",
            step="parse_sequence",
            outcome=outcome,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")

    system_state["core_heat"] = core_heat
    system_state["last_processed_timestamp"] = now_iso

    if new_processed_count > 0 or overload_occurred:
        if new_processed_count > 0:
            write_outputs_atomically(output_folder, json_output_path, csv_output_path, parsed_json, csv_rows, all_flattened_keys)

        save_ledger(ledger_path, {"ledger": ledger, "system_state": system_state})

    if overload_occurred:
        raise ThermalOverloadError(overload_error_msg)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}. Core heat: {core_heat:.1f}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

main = run_batch

if __name__ == '__main__':
    main()
