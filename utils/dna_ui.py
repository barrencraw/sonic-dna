#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
import getpass
from enum import Enum
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    NO_NEW_DNA = "NO_NEW_DNA"

def log_observability(chain_name, step, outcome, latency_ms=0, idempotency_key=None, error_message=None):
    """
    Standardized structured log for the DNA processing chain.
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": str(uuid.uuid4()),
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else str(outcome),
        "latency_ms": latency_ms,
        "actor_id": getpass.getuser(),
        "idempotency_key": idempotency_key
    }
    if error_message:
        log_entry["error_message"] = error_message

    print(f"[OBSERVABILITY] {json.dumps(log_entry)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if os.path.exists(input_path):
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
    """Raised when system heat is too high for certain DNA rules."""
    pass

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

def main(data_dir=None):
    start_time = time.time()
    chain_name = "dna_batch_chain"
    log_observability(chain_name, "main.start", Outcome.START)

    # Determine file paths
    if data_dir is None:
        project_root = os.getcwd()
        data_dir = os.path.join(project_root, 'data')
    else:
        project_root = os.path.dirname(data_dir)

    raw_folder = os.path.join(data_dir, 'raw')
    output_folder = os.path.join(data_dir, 'output')
    ledger_path = os.path.join(data_dir, 'processed_ledger.json')
    system_state_path = os.path.join(data_dir, 'system_state.json')

    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    try:
        rules_folder = os.path.join(project_root, 'rules')
        calculator = DNACalculator(rules_folder=rules_folder)
    except Exception as e:
        log_observability(chain_name, "rules_load", Outcome.ERROR, error_message=str(e))
        raise RuleLoadError(f"Could not load rules from {rules_folder}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(chain_name, "input_read", Outcome.ERROR, error_message=str(e))
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(chain_name, "input_check", Outcome.END)
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)

    # Load system state (Fatigue/Thermal System)
    system_heat = 0.0
    if os.path.exists(system_state_path):
        try:
            with open(system_state_path, 'r') as sf:
                state = json.load(sf)
                system_heat = state.get('system_heat', 0.0)
        except Exception:
            pass

    # Natural cooling: -1.0 per batch
    system_heat = max(0.0, system_heat - 1.0)

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
    seen_in_batch = set()

    for dna_str in dna_list:
        loop_start = time.time()
        idempotency_key = dna_str
        if idempotency_key in ledger or idempotency_key in seen_in_batch:
            outcome_val = ledger.get(idempotency_key, {}).get('terminal_outcome', 'already_seen_in_batch')
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={outcome_val}")
            log_observability(chain_name, "parse_loop", Outcome.SKIPPED, idempotency_key=idempotency_key)
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
        log_observability(chain_name, "parse_loop", Outcome.PROCESSING, idempotency_key=idempotency_key)
        seen_in_batch.add(idempotency_key)

        try:
            result = calculator.parse(dna_str)
            rule_name = result['rule']
            vals = result['values']

            # Fatigue System Logic
            if rule_name == "Volume":
                amp = vals.get('amp', 0)
                heat_gain = amp / 100.0
                system_heat += heat_gain

            if rule_name == "Clarity":
                if system_heat >= 10.0:
                    raise ThermalOverloadError(f"System thermal overload. Heat: {system_heat:.2f}/10.0. NEXT_ACTION_HINT: Allow system to cool. Natural dissipation active during idle cycles.")

                # Apply noise floor penalty: increase noise floor value (making it less negative)
                penalty = int(system_heat)
                if 'noise_floor' in vals and isinstance(vals['noise_floor'], dict):
                    original_val = vals['noise_floor'].get('value', 0)
                    vals['noise_floor']['value'] = max(0, original_val - penalty)
                    vals['noise_floor']['CONSEQUENCE_APPLIED'] = f"Thermal noise floor penalty: +{penalty}dB"

            entry = {
                'dna': dna_str,
                'rule': rule_name,
                'parsed': vals
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(rule_name, vals)
            flat['dna'] = dna_str
            flat['rule'] = rule_name
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS

        except ThermalOverloadError as e:
            outcome = Outcome.ERROR
            error_msg = str(e)
            parsed_json.append({'dna': dna_str, 'error': error_msg, 'REFUSAL_REASON': error_msg})
            flat = {'dna': dna_str, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        except RuleParseError as e:
            outcome = Outcome.ERROR
            error_msg = str(e)
            parsed_json.append({'dna': dna_str, 'error': error_msg})
            flat = {'dna': dna_str, 'error': error_msg}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        latency = int((time.time() - loop_start) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        log_observability(chain_name, "parse_complete", outcome, latency_ms=latency, idempotency_key=idempotency_key)
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome.value}")
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    # Always persist system state if we at least checked the DNA list
    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
        tmp_state = os.path.join(tmp_dir, 'system_state.json')

        try:
            # Always save heat
            with open(tmp_state, 'w') as sf:
                json.dump({'system_heat': system_heat}, sf)
            os.replace(tmp_state, system_state_path)

            if new_processed_count > 0:
                # 1) Write JSON
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) Write CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Write Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

        except Exception as e:
            log_observability(chain_name, "atomic_commit", Outcome.ERROR, error_message=str(e))
            raise PersistenceError("Failed to write output files atomically") from e

    total_latency = int((time.time() - start_time) * 1000)
    log_observability(chain_name, "main.end", Outcome.SUCCESS if new_processed_count > 0 else Outcome.NO_NEW_DNA, latency_ms=total_latency)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    if new_processed_count > 0:
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")
    print(f"     System Heat: {system_heat:.2f}")

if __name__ == '__main__':
    main()
