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

# ─── EXCEPTION TAXONOMY ───────────────────────────────────────────────────────

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger file fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file replacement fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal lockout threshold is reached."""
    pass


# ─── STATUS ENUM & UI MESSAGE KEYS ──────────────────────────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"


CONSEQUENCE_APPLIED_KEY = "Heat Accumulation"
REFUSAL_REASON_KEY = "Thermal Lockout"
NEXT_ACTION_HINT_KEY = "Wait for dissipation. The system is indifferent to your deadlines."

HEAT_PER_SEQUENCE = 2.0
MAX_HEAT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5


# ─── STRUCTURED LOGGING ───────────────────────────────────────────────────────

def log_structured(correlation_id=None, actor_id="batch_parser", chain_name="dna_batch_parser", step="process_batch", outcome="success", latency_ms=0, idempotency_key=None, outcome_detail=None):
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    log_entry = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail or {}
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")
    return log_entry


# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    dna_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_path}") from e
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Corrupted or unreadable ledger file: {ledger_path}") from e

        if isinstance(data, dict):
            if 'ledger' not in data:
                # Legacy flat ledger
                return {
                    'ledger': data,
                    'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}
                }
            else:
                state = data.get('system_state', {})
                if 'core_heat' not in state:
                    state['core_heat'] = 0.0
                if 'last_processed_timestamp' not in state:
                    state['last_processed_timestamp'] = None
                data['system_state'] = state
                if 'ledger' not in data:
                    data['ledger'] = {}
                return data
        else:
            raise LedgerLoadError(f"Invalid ledger schema in {ledger_path}")

    return {
        'ledger': {},
        'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}
    }

def save_ledger(ledger_path, ledger_data):
    try:
        tmp_ledger = f"{ledger_path}.tmp.{os.getpid()}"
        with open(tmp_ledger, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_ledger, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e


# ─── BATCH PARSER ENTRY POINT ─────────────────────────────────────────────────

def run_batch(correlation_id=None, actor_id="batch_parser"):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    start_time = time.time()

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return 0

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_list = read_input_file(input_file)
    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return 0

    full_ledger = load_ledger(ledger_path)
    ledger_entries = full_ledger['ledger']
    system_state = full_ledger['system_state']

    current_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Heat dissipation calculation
    if last_time_str:
        try:
            if 'T' in last_time_str:
                last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            else:
                last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = (now_utc - last_time).total_seconds()
            if elapsed_sec > 0:
                dissipated = elapsed_sec * COOLING_RATE_PER_SEC
                current_heat = max(0.0, current_heat - dissipated)
        except Exception:
            pass

    system_state['core_heat'] = current_heat
    system_state['last_processed_timestamp'] = now_iso

    # Determine which sequences are new (not already in ledger)
    unprocessed_sequences = [dna for dna in dna_list if dna not in ledger_entries]

    if unprocessed_sequences:
        if current_heat + HEAT_PER_SEQUENCE > MAX_HEAT_THRESHOLD or current_heat >= MAX_HEAT_THRESHOLD:
            # Thermal lockout
            save_ledger(ledger_path, full_ledger)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="thermal_check",
                outcome=DNAStatus.REFUSED.value,
                latency_ms=int((time.time() - start_time) * 1000),
                outcome_detail={
                    "current_heat": current_heat,
                    "max_threshold": MAX_HEAT_THRESHOLD,
                    "ui_message_keys": {
                        "refusal_reason": REFUSAL_REASON_KEY,
                        "next_action_hint": NEXT_ACTION_HINT_KEY
                    }
                }
            )
            raise ThermalOverloadError(f"{REFUSAL_REASON_KEY}: {NEXT_ACTION_HINT_KEY}")

    # Load existing JSON / CSV output
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
    for dna_seq in dna_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger_entries:
            terminal_outcome = ledger_entries[idempotency_key].get('terminal_outcome', 'skipped')
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="parse_sequence",
                outcome=DNAStatus.SKIPPED.value,
                idempotency_key=idempotency_key,
                outcome_detail={"reason": "already_processed", "terminal_outcome": terminal_outcome}
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if current_heat + HEAT_PER_SEQUENCE > MAX_HEAT_THRESHOLD:
            system_state['core_heat'] = current_heat
            save_ledger(ledger_path, full_ledger)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="thermal_check",
                outcome=DNAStatus.REFUSED.value,
                latency_ms=int((time.time() - start_time) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail={
                    "current_heat": current_heat,
                    "max_threshold": MAX_HEAT_THRESHOLD,
                    "ui_message_keys": {
                        "refusal_reason": REFUSAL_REASON_KEY,
                        "next_action_hint": NEXT_ACTION_HINT_KEY
                    }
                }
            )
            raise ThermalOverloadError(f"{REFUSAL_REASON_KEY}: {NEXT_ACTION_HINT_KEY}")

        current_heat += HEAT_PER_SEQUENCE
        system_state['core_heat'] = current_heat
        system_state['last_processed_timestamp'] = now_iso

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

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_iso,
            'dna_sequence': dna_seq,
            'dna': dna_seq
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parser",
            step="parse_sequence",
            outcome=outcome,
            idempotency_key=idempotency_key,
            outcome_detail={
                "core_heat": current_heat,
                "ui_message_keys": {
                    "consequence_applied": CONSEQUENCE_APPLIED_KEY
                }
            }
        )
        new_processed_count += 1

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

            except Exception as e:
                raise AtomicWriteError("Failed to write output files atomically") from e

        save_ledger(ledger_path, full_ledger)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger_entries)}")
    return new_processed_count

main = run_batch

if __name__ == '__main__':
    run_batch()
