#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
from utils.dna_calculator import DNACalculator, RuleParseError

MAX_HEAT = 100.0
HEAT_PER_SEQ = 20.0
COOLING_RATE = 2.0

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
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

import tempfile
import shutil

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
    """Raised when the system exceeds hardware heat limits (lockout)."""
    def __init__(self, message="Thermal Lockout", consequence="Heat Accumulation", hint="Wait for dissipation. The system is indifferent to your deadlines."):
        super().__init__(f"{message} (Consequence: {consequence}). Hint: {hint}")
        self.message = message
        self.consequence = consequence
        self.hint = hint
def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "system",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def load_ledger(ledger_path):
    default_ledger = {
        'system_heat': 0.0,
        'last_updated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'ledger': {}
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Check if structured
                    if 'ledger' in data and isinstance(data['ledger'], dict):
                        return data
                    else:
                        # Legacy flat ledger convert
                        default_ledger['ledger'] = data
                        return default_ledger
        except Exception:
            pass
    return default_ledger

def save_ledger(ledger_path, ledger_data):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger_data, f, indent=2)

def run_batch(correlation_id=None, actor_id="system"):
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

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    # Load ledger and perform thermal dissipation calculation
    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data['ledger']

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    last_time_str = ledger_data['last_updated']
    last_time = datetime.datetime.fromisoformat(last_time_str.replace('Z', '+00:00'))
    elapsed = (now_utc - last_time).total_seconds()
    if elapsed < 0:
        elapsed = 0.0

    current_heat = max(0.0, ledger_data['system_heat'] - elapsed * COOLING_RATE)
    ledger_data['system_heat'] = current_heat
    ledger_data['last_updated'] = now_str

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        # Save ledger to record cooling during idle cycles
        save_ledger(ledger_path, ledger_data)
        return

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

    from utils.dna_calculator import RuleParseError

    new_processed_count = 0
    error_to_raise = None

    try:
        for dna_str in dna_list:
            idempotency_key = dna_str
            start_time = time.perf_counter()

            if idempotency_key in ledger:
                last_outcome = ledger[idempotency_key]['terminal_outcome']
                if last_outcome in ('success', 'error'):
                    print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={last_outcome}")
                    log_structured(
                        correlation_id=correlation_id,
                        actor_id=actor_id,
                        chain_name="dna_batch_processing",
                        step="idempotency_check",
                        outcome="skipped",
                        latency_ms=0,
                        idempotency_key=idempotency_key,
                        outcome_detail=f"Deduplication hit. Already processed with outcome: {last_outcome}"
                    )
                    continue

            print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

            if current_heat >= MAX_HEAT:
                outcome = "refused"
                ledger[idempotency_key] = {
                    'terminal_outcome': outcome,
                    'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                }
                new_processed_count += 1
                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name="dna_batch_processing",
                    step="thermal_check",
                    outcome="refused",
                    latency_ms=0,
                    idempotency_key=idempotency_key,
                    outcome_detail="Thermal Lockout: Heat Accumulation"
                )
                raise ThermalOverloadError()

            try:
                result = calculator.parse(dna_str)
                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"
                outcome_detail = "DNA successfully parsed"

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_str,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "error"
                outcome_detail = str(e)

            current_heat += HEAT_PER_SEQ
            ledger_data['system_heat'] = current_heat

            ledger[idempotency_key] = {
                'terminal_outcome': outcome,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            new_processed_count += 1

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_processing",
                step="parse_dna",
                outcome=outcome,
                latency_ms=latency_ms,
                idempotency_key=idempotency_key,
                outcome_detail=outcome_detail
            )

    except Exception as e:
        error_to_raise = e

    # ATOMIC WRITE PATTERN:
    # 1. Write to a temporary directory in the same filesystem as the output folder
    # 2. Flush and sync files to ensure they are on disk
    # 3. Rename them to their final destination (atomic on most OSes)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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
                # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                persistence_error = PersistenceError("Failed to write output files atomically")
                if not error_to_raise:
                    error_to_raise = persistence_error

    print(f"[OK] Parsed {len(dna_list)} DNA strings.")

    # Always save ledger (even if 0 new sequences were processed, to record thermal dissipation)
    try:
        save_ledger(ledger_path, ledger_data)
    except Exception as e:
        if not error_to_raise:
            error_to_raise = PersistenceError("Failed to save ledger")

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

    if error_to_raise:
        raise error_to_raise

main = run_batch

if __name__ == '__main__':
    main()
