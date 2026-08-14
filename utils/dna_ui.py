#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when a ledger file exists but is corrupted."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when the mainframe's core heat exceeds the safety threshold."""
    pass

class DNAStatus(str, Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'

UI_MESSAGES = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

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

def load_ledger(ledger_path):
    """
    Loads the ledger from ledger_path.
    Returns a structured dictionary with 'ledger' and 'system_state' keys.
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Ledger file exists but is corrupted at {ledger_path}") from e

        if isinstance(data, dict):
            if "ledger" in data and "system_state" in data:
                return data
            else:
                # Convert legacy flat layout to structured format
                return {
                    "ledger": data,
                    "system_state": {"core_heat": 0.0, "last_processed_timestamp": ""}
                }
    return {
        "ledger": {},
        "system_state": {"core_heat": 0.0, "last_processed_timestamp": ""}
    }

def save_ledger(ledger_path, data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        raise PersistenceError(f"Failed to save ledger to {ledger_path}") from e

def log_structured(correlation_id=None, actor_id=None, chain_name=None, step=None, outcome=None, latency_ms=0, idempotency_key=None, outcome_detail=None):
    corr_id = correlation_id or "N/A"
    act_id = actor_id or "system"
    c_name = chain_name or "DNA Batch Parsing"
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    log_data = {
        "timestamp": timestamp,
        "correlation_id": corr_id,
        "actor_id": act_id,
        "chain_name": c_name,
        "step": step or "N/A",
        "outcome": outcome or "N/A",
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "N/A",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")

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

    # Read DNA sequences
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    # Load ledger and system state
    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data["ledger"]
    system_state = ledger_data["system_state"]

    core_heat = system_state.get('core_heat', 0.0)
    last_processed_timestamp = system_state.get('last_processed_timestamp', '')

    # Calculate heat dissipation
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_processed_timestamp:
        try:
            last_time = datetime.datetime.strptime(last_processed_timestamp, '%Y-%m-%dT%H:%M:%SZ')
            elapsed_seconds = (now - last_time).total_seconds()
            if elapsed_seconds > 0:
                dissipated = 0.5 * elapsed_seconds
                core_heat = max(0.0, core_heat - dissipated)
        except Exception:
            pass

    # Update system state with current (cooled down) core_heat
    system_state['core_heat'] = core_heat

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
    overload_occurred = False

    for dna_str in dna_sequence_list:
        idempotency_key = dna_str
        if idempotency_key in ledger:
            status = ledger[idempotency_key].get('terminal_outcome', '') if isinstance(ledger[idempotency_key], dict) else ledger[idempotency_key]
            # Skip if successfully processed or parsing failed permanently
            if status in [DNAStatus.SUCCESS, DNAStatus.ERROR, 'success', 'error']:
                print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={status}")
                continue

        # Check for Thermal Lockout before processing this sequence
        if core_heat >= 10.0:
            overload_occurred = True
            break

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")
        start_time = time.time()

        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values'],
                'dna_sequence': dna_str
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            flat['dna_sequence'] = dna_str
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS
            detail_msg = f"Parsed rule: {result['rule']}"

            # Consequence applied: accumulate heat
            core_heat += 2.0
            print(f"[{UI_MESSAGES['consequence_applied']}] Core heat increased to {core_heat:.1f}")

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': str(e),
                'dna_sequence': dna_str
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e), 'dna_sequence': dna_str}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR
            detail_msg = str(e)

        latency_ms = int((time.time() - start_time) * 1000)

        # Log structured telemetry
        log_structured(
            correlation_id=correlation_id,
            actor_id="system",
            chain_name="DNA Batch Parsing",
            step="Parse Sequence",
            outcome=outcome,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
            outcome_detail=detail_msg
        )

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    # Update system state values
    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = now_str

    print(f"[OK] Parsed {len(dna_sequence_list)} DNA sequences.")

    # Save ledger
    save_ledger(ledger_path, ledger_data)

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write to a temporary directory in the same filesystem as the output folder
        # 2. Flush and sync files to ensure they are on disk
        # 3. Rename them to their final destination (atomic on most OSes)

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
                # On Unix, os.replace is atomic. On Windows, it replaces if it exists.
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")
    if new_processed_count > 0:
        print(f"     JSON → {json_output_path}")
        print(f"     CSV  → {csv_output_path}")

    # Now raise the overload exception if we broke out of the loop
    if overload_occurred:
        raise ThermalOverloadError(
            f"{UI_MESSAGES['refusal_reason']}: Current core heat is {core_heat:.1f}. "
            f"{UI_MESSAGES['next_action_hint']}"
        )

# Maintain alias main for backward-compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
