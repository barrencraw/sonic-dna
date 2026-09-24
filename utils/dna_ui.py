#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
import sys
from datetime import datetime, timezone
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# ─── LOGGING & OBSERVABILITY HYGIENE ───────────────────────────

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail=None):
    """
    Standardized structured JSON log for batch DNA processing observability.
    Fields: timestamp, correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "system",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail or {}
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

# ─── CANONICAL TERMINAL STATES & STATUS ENUM ────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# ─── EXCEPTION TAXONOMY ─────────────────────────────────────────

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input file cannot be read."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files/ledger fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when reading ledger file fails or is corrupted."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file writes fail."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal fatigue limit is reached and system lock out occurs."""
    pass


# ─── FILE & LEDGER HELPERS ──────────────────────────────────────

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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}

def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e


# ─── BATCH PROCESSING ENTRY POINT ────────────────────────────────

def run_batch(correlation_id=None, actor_id="batch_parser"):
    chain_name = "dna_batch_parser"
    correlation_id = correlation_id or str(uuid.uuid4())
    start_time = time.time()

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id, actor_id, chain_name, "input_check",
            DNAStatus.SKIPPED.value, (time.time() - start_time) * 1000,
            None, {"reason": "Input file not found", "path": input_file}
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
        log_structured(
            correlation_id, actor_id, chain_name, "input_check",
            DNAStatus.SKIPPED.value, (time.time() - start_time) * 1000,
            None, {"reason": "No DNA sequences found in input file"}
        )
        return

    full_ledger_data = load_ledger(ledger_path)

    # Support backward compatibility if ledger file was legacy flat dict
    if "ledger" in full_ledger_data and isinstance(full_ledger_data["ledger"], dict):
        ledger = full_ledger_data["ledger"]
        system_state = full_ledger_data.get("system_state", {})
    else:
        ledger = full_ledger_data
        system_state = {}

    core_heat = system_state.get('core_heat', 0.0)
    last_time_str = system_state.get('last_processed_timestamp')

    # Thermal dissipation calculation (0.5 heat units per second)
    now_dt = datetime.now(timezone.utc)
    if last_time_str:
        try:
            last_dt = datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            elapsed_sec = (now_dt - last_dt).total_seconds()
            if elapsed_sec > 0:
                core_heat = max(0.0, core_heat - (elapsed_sec * 0.5))
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
    thermal_lockout = False
    lockout_reason = ""

    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        seq_start = time.time()

        if idempotency_key in ledger:
            prev_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            log_structured(
                correlation_id, actor_id, chain_name, "deduplication",
                DNAStatus.SKIPPED.value, (time.time() - seq_start) * 1000,
                idempotency_key, {"dedupe_hit": True, "terminal_outcome": prev_outcome}
            )
            continue

        # Check Thermal Fatigue Threshold ( lockout at 10.0 heat units )
        if core_heat >= 10.0:
            thermal_lockout = True
            lockout_reason = "Thermal Lockout"
            log_structured(
                correlation_id, actor_id, chain_name, "parse_sequence",
                DNAStatus.REFUSED.value, (time.time() - seq_start) * 1000,
                idempotency_key, {
                    "reason": lockout_reason,
                    "consequence": "Heat Accumulation",
                    "core_heat": core_heat,
                    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
                }
            )
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

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_seq
            flat['dna_sequence'] = dna_seq
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value

            # Thermal Heat accumulation: +2.0 units per parsed sequence
            core_heat += 2.0

        except RuleParseError as e:
            # On parse error, record as error entry
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
            'dna_sequence': dna_seq,
            'terminal_outcome': outcome,
            'timestamp': now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        new_processed_count += 1

        log_structured(
            correlation_id, actor_id, chain_name, "parse_sequence",
            outcome, (time.time() - seq_start) * 1000,
            idempotency_key, {"dna_sequence": dna_seq, "core_heat": core_heat}
        )

    # Save state if any new sequence was processed or system state updated
    if new_processed_count > 0:
        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

    # Always persist system state (core heat & timestamp)
    updated_ledger_data = {
        'ledger': ledger,
        'system_state': {
            'core_heat': core_heat,
            'last_processed_timestamp': now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
    }
    save_ledger(ledger_path, updated_ledger_data)

    total_latency_ms = (time.time() - start_time) * 1000
    log_structured(
        correlation_id, actor_id, chain_name, "batch_complete",
        DNAStatus.SUCCESS.value if not thermal_lockout else DNAStatus.REFUSED.value,
        total_latency_ms, None,
        {"new_processed_count": new_processed_count, "total_ledger_entries": len(ledger), "core_heat": core_heat}
    )

    if thermal_lockout:
        raise ThermalOverloadError(
            f"Thermal Lockout: Core heat threshold exceeded ({core_heat:.1f} >= 10.0). "
            "Wait for dissipation. The system is indifferent to your deadlines."
        )

# Main alias for backward compatibility
main = run_batch

if __name__ == '__main__':
    main()
