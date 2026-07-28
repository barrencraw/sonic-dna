#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
from utils.dna_calculator import DNACalculator, RuleParseError

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

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when physical thermal fatigue threshold is breached."""
    def __init__(self, message="Thermal Lockout"):
        super().__init__(message)
        self.consequence = "Heat Accumulation"
        self.reason = "Thermal Lockout"
        self.hint = "Wait for dissipation. The system is indifferent to your deadlines."

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    dir_name = os.path.dirname(ledger_path)
    ensure_folder(dir_name)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".ledger_tmp_", suffix=".json")
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ledger_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically: {e}") from e

def log_structured(correlation_id=None, actor_id="system", chain_name="DNA Batch Parsing", step="Process Sequence", outcome="success", latency_ms=0, idempotency_key=None, outcome_detail=None):
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

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

    # Read DNA strings
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        return

    ledger = load_ledger(ledger_path)

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

    # Load Thermal Fatigue State
    system_state = ledger.get('system_state', {
        'heat': 0.0,
        'last_processed_timestamp': None,
        'lockout': False
    })
    heat = system_state.get('heat', 0.0)
    lockout = system_state.get('lockout', False)
    last_processed_timestamp = system_state.get('last_processed_timestamp', None)

    now = datetime.datetime.now(datetime.timezone.utc)
    now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Dissipate heat based on elapsed time since last_processed_timestamp
    if last_processed_timestamp:
        last_time_str = last_processed_timestamp
        if last_time_str.endswith('Z'):
            last_time_str = last_time_str[:-1] + '+00:00'
        last_time = datetime.datetime.fromisoformat(last_time_str)
        elapsed = (now - last_time).total_seconds()
        if elapsed > 0:
            heat = max(0.0, heat - elapsed * 5.0)  # 5.0 units per second cooling

    if lockout and heat < 50.0:
        lockout = False

    new_processed_count = 0
    error_to_raise = None

    try:
        for dna_sequence in dna_sequence_list:
            ledger_entries = ledger.get('ledger', ledger)
            if dna_sequence in ledger_entries:
                log_structured(
                    correlation_id=correlation_id,
                    actor_id="system",
                    chain_name="DNA Batch Parsing",
                    step="Process Sequence",
                    outcome="skipped",
                    latency_ms=0,
                    idempotency_key=dna_sequence,
                    outcome_detail="Deduplication hit. Sequence already processed."
                )
                continue

            # Check lockout state
            if lockout:
                error_to_raise = ThermalOverloadError("Thermal Lockout")
                break

            start_time = time.perf_counter()
            try:
                result = calculator.parse(dna_sequence)
                entry = {
                    'dna': dna_sequence,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_sequence
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "success"

            except RuleParseError as e:
                parsed_json.append({
                    'dna': dna_sequence,
                    'error': str(e)
                })
                flat = {'dna': dna_sequence, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = "error"

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Update heat and ledger
            heat += 20.0

            if 'ledger' not in ledger:
                # Migrate legacy flat entries if exist
                legacy_entries = {k: v for k, v in ledger.items() if k not in ('system_state', 'ledger')}
                ledger['ledger'] = legacy_entries

            ledger['ledger'][dna_sequence] = {
                'terminal_outcome': outcome,
                'timestamp': now_str
            }
            new_processed_count += 1

            log_structured(
                correlation_id=correlation_id,
                actor_id="system",
                chain_name="DNA Batch Parsing",
                step="Process Sequence",
                outcome=outcome,
                latency_ms=latency_ms,
                idempotency_key=dna_sequence,
                outcome_detail=f"Heat Accumulation: {heat:.1f}C"
            )

            # Check heat limit
            if heat >= 100.0:
                lockout = True
                error_to_raise = ThermalOverloadError("Thermal Lockout")
                break

    except Exception as e:
        error_to_raise = e

    # Update state
    system_state['heat'] = heat
    system_state['lockout'] = lockout
    system_state['last_processed_timestamp'] = now_str
    ledger['system_state'] = system_state

    # Save ledger atomically (includes updated system_state even if zero processed)
    try:
        save_ledger(ledger_path, ledger)
    except Exception as se:
        if error_to_raise is None:
            error_to_raise = se

    # Atomic write of JSON and CSV outputs only if we actually processed new items
    if new_processed_count > 0:
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
            except Exception as pe:
                if error_to_raise is None:
                    error_to_raise = PersistenceError(f"Failed to write output files atomically: {pe}")

    if error_to_raise:
        raise error_to_raise

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger.get('ledger', ledger))}")

main = run_batch

if __name__ == '__main__':
    run_batch()
