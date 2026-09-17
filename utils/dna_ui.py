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

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

    def __str__(self):
        return self.value

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input sequence file fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when core heat exceeds safety lockout threshold."""
    pass

class PersistenceError(DNAProcessingError):
    """Base exception for persistence / atomic write failures."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when ledger loading fails due to corruption or read error."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic write for output JSON or CSV fails."""
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

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms=0, idempotency_key="", outcome_detail=""):
    """
    Emits structured telemetry JSON log prefixed with 'JSON_LOG:'.
    """
    utc_now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    outcome_str = outcome.value if isinstance(outcome, DNAStatus) else str(outcome)
    payload = {
        "timestamp": utc_now,
        "correlation_id": correlation_id or "",
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name or "dna_batch_parser",
        "step": step,
        "outcome": outcome_str,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key or "",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(payload)}")

def load_ledger(ledger_path):
    """
    Loads processed ledger. Returns dict structured as:
    {'ledger': {...}, 'system_state': {'core_heat': float, 'last_processed_timestamp': str}}
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                content = json.load(f)
                if isinstance(content, dict):
                    if "ledger" in content and "system_state" in content:
                        return content
                    else:
                        # Legacy flat ledger structure
                        return {
                            "ledger": content,
                            "system_state": {
                                "core_heat": 0.0,
                                "last_processed_timestamp": ""
                            }
                        }
                return {
                    "ledger": {},
                    "system_state": {
                        "core_heat": 0.0,
                        "last_processed_timestamp": ""
                    }
                }
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger at {ledger_path}: {e}") from e
    return {
        "ledger": {},
        "system_state": {
            "core_heat": 0.0,
            "last_processed_timestamp": ""
        }
    }

def save_ledger(ledger_path, ledger_state):
    """
    Saves ledger state atomically to ledger_path using tempfile + replace.
    """
    dir_name = os.path.dirname(ledger_path) or "."
    ensure_folder(dir_name)
    try:
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
            tmp_name = tf.name
            json.dump(ledger_state, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_name, ledger_path)
    except Exception as e:
        if 'tmp_name' in locals() and os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    log_structured(correlation_id, actor_id, "dna_batch_parser", "start", DNAStatus.SUCCESS, outcome_detail="Starting batch parse chain")

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(correlation_id, actor_id, "dna_batch_parser", "end", DNAStatus.SKIPPED, outcome_detail=f"Input file not found: {input_file}")
        print(f"[ERROR] Input file not found: {input_file}")
        return

    # Load Calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(correlation_id, actor_id, "dna_batch_parser", "error", DNAStatus.ERROR, outcome_detail=f"Rule load failure: {e}")
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        log_structured(correlation_id, actor_id, "dna_batch_parser", "end", DNAStatus.SKIPPED, outcome_detail="No DNA sequences found in toSequence.txt")
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    # Load Ledger & State
    full_ledger_state = load_ledger(ledger_path)
    ledger = full_ledger_state["ledger"]
    system_state = full_ledger_state["system_state"]

    core_heat = float(system_state.get("core_heat", 0.0))
    last_processed_timestamp = system_state.get("last_processed_timestamp", "")

    # Calculate thermal dissipation
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_processed_timestamp:
        try:
            last_dt = datetime.datetime.strptime(last_processed_timestamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (now_dt - last_dt).total_seconds())
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
    initial_ledger = dict(ledger)

    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(correlation_id, actor_id, "dna_batch_parser", "parse_item", DNAStatus.SKIPPED, idempotency_key=idempotency_key, outcome_detail="Duplicate sequence skipped")
            continue

        # Check Thermal Fatigue boundary before processing new sequence
        if core_heat + 2.0 > 10.0:
            system_state["core_heat"] = core_heat
            system_state["last_processed_timestamp"] = now_str
            save_ledger(ledger_path, {"ledger": initial_ledger, "system_state": system_state})

            refusal_msg = "Thermal Lockout: Wait for dissipation. The system is indifferent to your deadlines."
            log_structured(correlation_id, actor_id, "dna_batch_parser", "parse_item", DNAStatus.REFUSED, idempotency_key=idempotency_key, outcome_detail=refusal_msg)
            print(f"[ERROR] {refusal_msg}")
            raise ThermalOverloadError(refusal_msg)

        # Apply Heat Accumulation
        core_heat += 2.0
        print(f"[Thermal System] Heat Accumulation: +2.0 heat units (Current Core Heat: {core_heat:.1f}/10.0)")

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

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

        ledger[idempotency_key] = {
            'terminal_outcome': outcome.value if isinstance(outcome, DNAStatus) else str(outcome),
            'timestamp': now_str
        }
        new_processed_count += 1
        last_processed_timestamp = now_str
        log_structured(correlation_id, actor_id, "dna_batch_parser", "parse_item", outcome, idempotency_key=idempotency_key, outcome_detail=f"Parsed with status {outcome}")

    system_state["core_heat"] = core_heat
    system_state["last_processed_timestamp"] = last_processed_timestamp

    # Only rewrite output files and save ledger if new items were processed
    if new_processed_count > 0:
        log_structured(correlation_id, actor_id, "dna_batch_parser", "persist_outputs", DNAStatus.SUCCESS, outcome_detail=f"Persisting {new_processed_count} new sequence entries")
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
                log_structured(correlation_id, actor_id, "dna_batch_parser", "persist_outputs", DNAStatus.ERROR, outcome_detail=f"Atomic write error: {e}")
                raise AtomicWriteError(f"Failed to write output files atomically: {e}") from e

        save_ledger(ledger_path, {"ledger": ledger, "system_state": system_state})

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_structured(correlation_id, actor_id, "dna_batch_parser", "end", DNAStatus.SUCCESS, latency_ms=elapsed_ms, outcome_detail=f"Processed {new_processed_count} new sequences.")
    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    run_batch()
