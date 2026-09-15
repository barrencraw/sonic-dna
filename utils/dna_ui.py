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

# ─── ENUMS & STATUS CODES ───────────────────────────────────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# ─── TYPED EXCEPTION TAXONOMY ─────────────────────────────────────────────────

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input DNA sequences fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when heat accumulation exceeds safety lockout threshold."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading the processed ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic write operations fail."""
    pass

# ─── OBSERVABILITY & STRUCTURED LOGGING ─────────────────────────────────────

def log_structured(correlation_id, chain_name, step, outcome, latency_ms, actor_id, idempotency_key, outcome_detail=None):
    """
    Emits structured JSON logs with a standard prefix for parsing and searchability.
    """
    now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_entry = {
        "timestamp": now_utc,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

# ─── FILE & LEDGER HELPERS ───────────────────────────────────────────────────

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
    """
    Loads ledger file and returns structured representation with system state.
    Supports backward compatibility with legacy flat ledger dicts.
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    raise LedgerLoadError("Ledger root is not a dictionary.")
                if 'ledger' in data and 'system_state' in data:
                    return data
                else:
                    # Legacy flat format
                    return {
                        'ledger': data,
                        'system_state': {
                            'core_heat': 0.0,
                            'last_processed_timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                        }
                    }
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Corrupted JSON in ledger file: {ledger_path}") from e
        except PersistenceError:
            raise
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {
        'ledger': {},
        'system_state': {
            'core_heat': 0.0,
            'last_processed_timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
    }

def save_ledger(ledger_path, ledger_structure):
    """
    Saves structured ledger to disk.
    """
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_structure, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

# ─── BATCH PROCESSOR CHAIN ────────────────────────────────────────────────────

def run_batch(correlation_id=None, actor_id="batch_parser"):
    chain_start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())
    chain_name = "dna_batch_parser"

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, chain_name, "input_check", DNAStatus.SKIPPED, 0, actor_id, None, "Input file not found")
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, chain_name, "init_rules", DNAStatus.ERROR, 0, actor_id, None, str(e))
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        log_structured(correlation_id, chain_name, "read_input", DNAStatus.SKIPPED, 0, actor_id, None, "No DNA sequences found")
        return

    full_ledger = load_ledger(ledger_path)
    initial_ledger = dict(full_ledger.get('ledger', {}))
    ledger = dict(initial_ledger)
    system_state = dict(full_ledger.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': ''}))

    # Calculate thermal dissipation
    last_time_str = system_state.get('last_processed_timestamp', '')
    core_heat = float(system_state.get('core_heat', 0.0))
    now_dt = datetime.now(timezone.utc)
    if last_time_str:
        try:
            last_dt = datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            elapsed_seconds = max(0.0, (now_dt - last_dt).total_seconds())
            cooling = elapsed_seconds * 0.5  # Cools down 0.5 heat units per second
            core_heat = max(0.0, core_heat - cooling)
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
        idempotency_key = dna_seq
        seq_start_time = time.time()

        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED)
            log_structured(
                correlation_id, chain_name, "deduplication", DNAStatus.SKIPPED,
                int((time.time() - seq_start_time) * 1000), actor_id, idempotency_key,
                f"Deduplicated (previous outcome: {term_outcome})"
            )
            continue

        # Check thermal fatigue lockout threshold (10.0 heat units)
        if core_heat + 2.0 > 10.0:
            system_state['core_heat'] = core_heat
            system_state['last_processed_timestamp'] = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            # Rollback uncommitted sequence entries to maintain ledger/output atomicity
            save_ledger(ledger_path, {'ledger': initial_ledger, 'system_state': system_state})

            log_structured(
                correlation_id, chain_name, "thermal_check", DNAStatus.REFUSED,
                int((time.time() - seq_start_time) * 1000), actor_id, idempotency_key,
                "Thermal Lockout"
            )
            print("[CONSEQUENCE] Heat Accumulation")
            print("[REFUSAL REASON] Thermal Lockout")
            print("[NEXT ACTION HINT] Wait for dissipation. The system is indifferent to your deadlines.")
            raise ThermalOverloadError("Thermal Lockout")

        # Accumulate heat per sequence processed
        core_heat += 2.0

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
            outcome = DNAStatus.SUCCESS

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

        latency_ms = int((time.time() - seq_start_time) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        new_processed_count += 1

        log_structured(
            correlation_id, chain_name, "parse_sequence", outcome.value,
            latency_ms, actor_id, idempotency_key, f"Outcome: {outcome.value}"
        )

    # Persist outputs atomically if new items processed
    if new_processed_count > 0:
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

        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        save_ledger(ledger_path, {'ledger': ledger, 'system_state': system_state})

    total_latency_ms = int((time.time() - chain_start_time) * 1000)
    log_structured(
        correlation_id, chain_name, "chain_complete", DNAStatus.SUCCESS.value,
        total_latency_ms, actor_id, None, f"Processed {new_processed_count} sequences"
    )

main = run_batch

if __name__ == '__main__':
    run_batch()
