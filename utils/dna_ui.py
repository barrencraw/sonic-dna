#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
from dataclasses import dataclass, asdict
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError
from utils.integrity_manager import IntegrityManager

class Outcome(Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    START = "start"
    END = "end"
    NO_NEW_DNA = "no_new_dna"
    WARN = "warn"
    REFUSAL = "refusal"

@dataclass
class ProcessingResult:
    dna: str
    outcome: Outcome
    rule: str = None
    values: dict = None
    error_msg: str = None

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_list = []
    if not os.path.exists(input_path):
        return dna_list
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
    return dna_list

def flatten_parsed(rule_name, values_dict, parent_key=''):
    items = {}
    for k, v in values_dict.items():
        new_key = f"{parent_key}.{k}" if parent_key else f"{rule_name}.{k}"
        if isinstance(v, dict):
            items.update(flatten_parsed(rule_name, v, new_key))
        else:
            items[new_key] = v
    return items

def log_obs(correlation_id, actor_id, step, outcome, latency_ms=0, dna=None, error_msg=None, extra=None):
    log_data = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "chain_name": "dna_batch_chain",
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "latency_ms": latency_ms
    }
    if dna:
        log_data["idempotency_key"] = dna
    if error_msg:
        log_data["error"] = error_msg
    if extra:
        log_data.update(extra)

    print(f"[OBSERVABILITY] {json.dumps(log_data)}")

def load_system_messages(project_root):
    msg_path = os.path.join(project_root, 'data', 'system_messages.json')
    if os.path.exists(msg_path):
        try:
            with open(msg_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def main(correlation_id=None, actor_id="system"):
    start_time = time.time()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    integrity_path = os.path.join(project_root, 'data', 'system_integrity.json')
    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    log_obs(correlation_id, actor_id, "START", Outcome.START)

    messages = load_system_messages(project_root)

    # Instantiate managers
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_obs(correlation_id, actor_id, "INIT", Outcome.ERROR, error_msg=str(e))
        raise RuleLoadError(f"Could not load rules") from e

    integrity_manager = IntegrityManager(state_file=integrity_path)

    # Read DNA strings
    input_file = os.path.join(raw_folder, 'toSequence.txt')
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_obs(correlation_id, actor_id, "READ", Outcome.ERROR, error_msg=str(e))
        raise DNAProcessingError(f"Failed to read input file") from e

    if not dna_list:
        log_obs(correlation_id, actor_id, "PROCESS", Outcome.NO_NEW_DNA)
        print("[OK] No DNA to process.")
        return

    # Load existing state
    ledger = {}
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                ledger = json.load(f)
        except Exception:
            pass

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as f:
                parsed_json = json.load(f)
        except Exception:
            pass

    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')
    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    csv_rows = list(reader)
        except Exception:
            pass

    new_processed_count = 0
    for dna_str in dna_list:
        step_start = time.time()
        if dna_str in ledger:
            print(f"[Idempotency] key={dna_str} dedupe_hit=True terminal_outcome={ledger[dna_str]['terminal_outcome']}")
            continue

        # Preliminary parse for integrity check
        current_rule = None
        current_values = {}
        is_maintenance = False
        parse_error = None

        try:
            parse_result = calculator.parse(dna_str)
            current_rule = parse_result['rule']
            current_values = parse_result['values']
            is_maintenance = integrity_manager.is_maintenance_dna(current_rule, current_values)
        except RuleParseError as e:
            parse_error = e

        # Refusal check
        if integrity_manager.get_integrity() <= 0 and not is_maintenance:
            log_obs(correlation_id, actor_id, "PARSE", Outcome.REFUSAL, dna=dna_str, extra={
                "system_msg": messages.get("refusal_reason", "Integrity depleted."),
                "next_action_hint": messages.get("next_action_hint", "Perform maintenance.")
            })
            print(f"[REFUSAL] key={dna_str} reason=Integrity depleted")
            continue

        print(f"[Idempotency] key={dna_str} dedupe_hit=False terminal_outcome=processing")

        outcome = Outcome.SUCCESS
        error_msg = None

        if parse_error:
            outcome = Outcome.ERROR
            error_msg = f"ERROR: {str(parse_error)}"
            parsed_json.append({'dna': dna_str, 'error': str(parse_error)})
            flat = {'dna': dna_str, 'error': str(parse_error)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            current_rule = "unknown"
            current_values = {}
        else:
            entry = {'dna': dna_str, 'rule': current_rule, 'parsed': current_values}
            parsed_json.append(entry)

            flat = flatten_parsed(current_rule, current_values)
            flat['dna'] = dna_str
            flat['rule'] = current_rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        # Apply wear
        integrity_manager.calculate_wear(outcome.value, current_rule, current_values)

        # Record in ledger
        ledger[dna_str] = {
            'terminal_outcome': error_msg if outcome == Outcome.ERROR else outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        latency = int((time.time() - step_start) * 1000)
        extra_obs = {}
        if outcome == Outcome.SUCCESS:
            extra_obs["system_msg"] = messages.get("consequence_applied", "Wear applied.")

        log_obs(correlation_id, actor_id, "PARSE", outcome, latency_ms=latency, dna=dna_str, error_msg=error_msg, extra=extra_obs)
        new_processed_count += 1

    # Atomic Commit
    with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
        tmp_json = os.path.join(tmp_dir, 'output.json')
        tmp_csv = os.path.join(tmp_dir, 'output.csv')
        tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
        tmp_integrity = os.path.join(tmp_dir, 'integrity.json')

        try:
            with open(tmp_json, 'w', encoding='utf-8') as f:
                json.dump(parsed_json, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            fieldnames = sorted(all_flattened_keys)
            with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in csv_rows:
                    writer.writerow({k: row.get(k, '') for k in fieldnames})
                f.flush()
                os.fsync(f.fileno())

            with open(tmp_ledger, 'w', encoding='utf-8') as f:
                json.dump(ledger, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            with open(tmp_integrity, 'w', encoding='utf-8') as f:
                json.dump(integrity_manager.get_state(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_json, json_output_path)
            os.replace(tmp_csv, csv_output_path)
            os.replace(tmp_ledger, ledger_path)
            os.replace(tmp_integrity, integrity_path)
        except Exception as e:
            log_obs(correlation_id, actor_id, "COMMIT", Outcome.ERROR, error_msg=str(e))
            raise PersistenceError("Atomic commit failed") from e

    total_latency = int((time.time() - start_time) * 1000)
    log_obs(correlation_id, actor_id, "END", Outcome.END, latency_ms=total_latency)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
