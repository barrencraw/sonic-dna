#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import uuid
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# ─── EXCEPTION TAXONOMY ────────────────────────────────────────────────────────

class DNAProcessingError(Exception):
    """Base exception for all DNA processing failures."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded from disk."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input files cannot be read."""
    pass

class PersistenceError(DNAProcessingError):
    """Base exception for persistence / disk write failures."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when the processed ledger file is corrupted or unreadable."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file persistence fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when systemic core heat exceeds safety lockout thresholds."""
    pass

# ─── CONSTANTS & UI MESSAGES ───────────────────────────────────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

UI_MESSAGES = {
    "consequence_applied": "Heat Accumulation",
    "refusal_reason": "Thermal Lockout",
    "next_action_hint": "Wait for dissipation. The system is indifferent to your deadlines."
}

# ─── STRUCTURED LOGGING ────────────────────────────────────────────────────────

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms=0, idempotency_key="", outcome_detail=""):
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name or "dna_batch_parser",
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_entry)}")

# ─── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

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
    """
    Loads ledger file.
    Returns dictionary with keys 'ledger' and 'system_state'.
    Raises LedgerLoadError if corrupted.
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger at {ledger_path}") from e

        if isinstance(data, dict):
            if "ledger" in data and "system_state" in data:
                return data
            else:
                # Legacy flat format
                return {
                    "ledger": data,
                    "system_state": {
                        "core_heat": 0.0,
                        "last_processed_timestamp": None
                    }
                }
        else:
            raise LedgerLoadError(f"Invalid ledger format in {ledger_path}")
    return {
        "ledger": {},
        "system_state": {
            "core_heat": 0.0,
            "last_processed_timestamp": None
        }
    }

def save_ledger(ledger_path, data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

# ─── BATCH PARSER ENTRYPOINT ───────────────────────────────────────────────────

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    dna_list = read_input_file(input_file)
    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data.get("ledger", {})
    system_state = ledger_data.get("system_state", {"core_heat": 0.0, "last_processed_timestamp": None})

    core_heat = float(system_state.get("core_heat", 0.0))
    last_time_str = system_state.get("last_processed_timestamp")

    now = datetime.datetime.now(datetime.timezone.utc)
    now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_time_str:
        try:
            last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = (now - last_time).total_seconds()
            if elapsed_sec > 0:
                dissipated = elapsed_sec * 0.5
                core_heat = max(0.0, core_heat - dissipated)
        except Exception:
            pass

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

    for dna_sequence in dna_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            log_structured(correlation_id, "batch_parser", "dna_batch_parser", "dedupe_check", DNAStatus.SKIPPED.value, 0, idempotency_key, "Deduplication hit")
            continue

        # Check Thermal Lockout before processing new sequence
        if core_heat >= 10.0:
            system_state["core_heat"] = core_heat
            system_state["last_processed_timestamp"] = now_str
            save_ledger(ledger_path, {"ledger": ledger, "system_state": system_state})
            log_structured(correlation_id, "batch_parser", "dna_batch_parser", "thermal_check", DNAStatus.REFUSED.value, 0, idempotency_key, UI_MESSAGES["refusal_reason"])
            raise ThermalOverloadError(UI_MESSAGES["refusal_reason"])

        start_t = time.time()
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS.value

            # Add heat for successfully parsed sequence
            core_heat += 2.0

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value

        latency = int((time.time() - start_t) * 1000)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }
        log_structured(correlation_id, "batch_parser", "dna_batch_parser", "process_sequence", outcome, latency, idempotency_key, outcome)
        new_processed_count += 1

    system_state["core_heat"] = core_heat
    system_state["last_processed_timestamp"] = now_str

    if new_processed_count > 0:
        # Atomic output persistence
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

        save_ledger(ledger_path, {"ledger": ledger, "system_state": system_state})

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}. Core Heat: {core_heat:.1f}")

main = run_batch

if __name__ == '__main__':
    main()
