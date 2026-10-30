#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import uuid
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# Standardized UI Message Keys
MESSAGE_KEY_CONSEQUENCE = "Heat Accumulation"
MESSAGE_KEY_REFUSAL_REASON = "Thermal Lockout"
MESSAGE_KEY_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# DNA Status Enum
class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# Exception Taxonomy
class DNAProcessingError(Exception):
    """Base exception for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input DNA file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base exception for persistence failures."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading processed ledger fails due to corruption."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic output writing fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when mainframe core heat reaches or exceeds safety lockout threshold."""
    def __init__(self, message=MESSAGE_KEY_REFUSAL_REASON, current_heat=0.0):
        super().__init__(message)
        self.consequence = MESSAGE_KEY_CONSEQUENCE
        self.refusal_reason = MESSAGE_KEY_REFUSAL_REASON
        self.next_action_hint = MESSAGE_KEY_NEXT_ACTION_HINT
        self.current_heat = current_heat

def log_structured(correlation_id=None, actor_id="batch_parser", chain_name="dna_batch_parser", step="parse", outcome="success", latency_ms=0, idempotency_key=None, outcome_detail=None):
    """Emits structured JSON telemetry log prefixed with JSON_LOG:"""
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads input file under data/raw; each line is one DNA sequence.
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
    items = {}
    for k, v in values_dict.items():
        new_key = f"{parent_key}.{k}" if parent_key else f"{rule_name}.{k}"
        if isinstance(v, dict):
            items.update(flatten_parsed(rule_name, v, new_key))
        else:
            items[new_key] = v
    return items

def parse_utc_timestamp(ts_str):
    if not ts_str:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S'):
        try:
            dt = datetime.datetime.strptime(ts_str, fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    return None

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    raise LedgerLoadError("Ledger root is not a dictionary")
                if "ledger" in data:
                    ledger = data.get("ledger", {})
                    system_state = data.get("system_state", {"core_heat": 0.0, "last_processed_timestamp": None})
                    return ledger, system_state
                else:
                    # Legacy flat layout
                    return data, {"core_heat": 0.0, "last_processed_timestamp": None}
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Corrupted ledger JSON at {ledger_path}") from e
        except Exception as e:
            if isinstance(e, LedgerLoadError):
                raise
            raise LedgerLoadError(f"Failed to load ledger: {e}") from e
    return {}, {"core_heat": 0.0, "last_processed_timestamp": None}

def save_ledger(ledger_path, ledger, system_state):
    try:
        payload = {
            "ledger": ledger,
            "system_state": system_state
        }
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def atomic_write_outputs(output_folder, json_output_path, csv_output_path, parsed_json, csv_rows, fieldnames):
    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')

        try:
            with open(tmp_json, 'w', encoding='utf-8') as jf:
                json.dump(parsed_json, jf, indent=2)
                jf.flush()
                os.fsync(jf.fileno())

            sorted_fields = sorted(fieldnames)
            with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                writer = csv.DictWriter(cf, fieldnames=sorted_fields)
                writer.writeheader()
                for row in csv_rows:
                    out = {k: row.get(k, '') for k in sorted_fields}
                    writer.writerow(out)
                cf.flush()
                os.fsync(cf.fileno())

            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
        except Exception as e:
            raise AtomicWriteError("Failed to write output files atomically") from e

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')

    # Paths defined unconditionally
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger, system_state = load_ledger(ledger_path)

    # Calculate thermal decay
    HEAT_PER_SEQUENCE = 2.0
    DISSIPATION_RATE = 0.5
    LOCKOUT_THRESHOLD = 10.0

    current_heat = float(system_state.get("core_heat", 0.0))
    last_time_str = system_state.get("last_processed_timestamp")
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    if last_time_str:
        last_dt = parse_utc_timestamp(last_time_str)
        if last_dt:
            elapsed = max(0.0, (now_utc - last_dt).total_seconds())
            current_heat = max(0.0, current_heat - DISSIPATION_RATE * elapsed)

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
        except Exception:
            parsed_json = []

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
        if idempotency_key in ledger:
            prev = ledger[idempotency_key]
            term_outcome = prev.get('terminal_outcome', DNAStatus.SUCCESS.value) if isinstance(prev, dict) else DNAStatus.SUCCESS.value
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome=DNAStatus.SKIPPED.value,
                outcome_detail="deduplicated"
            )
            continue

        # Check thermal lockout before processing
        if current_heat + HEAT_PER_SEQUENCE >= LOCKOUT_THRESHOLD:
            # Commit mid-batch progress if any sequences were processed so far
            now_utc_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
            updated_state = {
                "core_heat": current_heat,
                "last_processed_timestamp": now_utc_str
            }
            if new_processed_count > 0:
                atomic_write_outputs(output_folder, json_output_path, csv_output_path, parsed_json, csv_rows, all_flattened_keys)
                save_ledger(ledger_path, ledger, updated_state)

            log_structured(
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome=DNAStatus.REFUSED.value,
                outcome_detail=MESSAGE_KEY_REFUSAL_REASON
            )
            raise ThermalOverloadError(MESSAGE_KEY_REFUSAL_REASON, current_heat=current_heat)

        # Process sequence
        t0 = time.time()
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
            outcome_detail = f"parsed rule {result['rule']}"
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

            outcome = DNAStatus.ERROR.value
            outcome_detail = str(e)

        current_heat += HEAT_PER_SEQUENCE
        now_utc_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1
        latency_ms = int((time.time() - t0) * 1000)

        log_structured(
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            outcome=outcome,
            latency_ms=latency_ms,
            outcome_detail=outcome_detail
        )

    # Atomic write output and update ledger if new items were processed
    now_utc_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    system_state = {
        "core_heat": current_heat,
        "last_processed_timestamp": now_utc_str
    }

    if new_processed_count > 0:
        atomic_write_outputs(output_folder, json_output_path, csv_output_path, parsed_json, csv_rows, all_flattened_keys)
        save_ledger(ledger_path, ledger, system_state)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}. Core heat: {current_heat:.1f}")

main = run_batch

if __name__ == '__main__':
    main()
