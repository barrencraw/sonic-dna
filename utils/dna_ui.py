#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import datetime
import uuid
from utils.dna_calculator import DNACalculator, RuleParseError
from utils.integrity_manager import IntegrityManager

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_list = []
    if not os.path.exists(input_path):
        return []
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

class DNAProcessingError(Exception):
    pass

class RuleLoadError(DNAProcessingError):
    pass

class PersistenceError(DNAProcessingError):
    pass

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def log_observability(correlation_id, actor_id, step, outcome, idempotency_key=None, latency_ms=0, system_msg=None):
    log_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "chain": "dna_batch_chain",
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms
    }
    if idempotency_key:
        log_data["idempotency_key"] = idempotency_key
    if system_msg:
        log_data["system_msg"] = system_msg
    print(f"[OBSERVABILITY] {json.dumps(log_data)}")

def main(correlation_id=None, actor_id=None):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    if not actor_id:
        actor_id = "standalone"

    log_observability(correlation_id, actor_id, "batch_start", "START")

    project_root = os.getcwd()
    data_folder = os.path.join(project_root, 'data')
    system_msgs_path = os.path.join(data_folder, 'system_messages.json')
    system_msgs = {}
    if os.path.exists(system_msgs_path):
        try:
            with open(system_msgs_path, 'r', encoding='utf-8') as f:
                system_msgs = json.load(f)
        except Exception:
            pass

    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    integrity_path = os.path.join(project_root, 'data', 'system_integrity.json')
    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, actor_id, "load_rules", "ERROR")
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Instantiate Integrity Manager
    integrity_manager = IntegrityManager(integrity_path)

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(correlation_id, actor_id, "read_input", "ERROR")
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(correlation_id, actor_id, "batch_end", "NO_NEW_DATA")
        return

    ledger = load_ledger(ledger_path)

    # Load existing JSON output
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

    # Load existing CSV rows
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
    for dna_str in dna_list:
        start_time = time.time()
        idempotency_key = dna_str

        if idempotency_key in ledger:
            log_observability(correlation_id, actor_id, "process_dna", "DEDUPE", idempotency_key=idempotency_key)
            continue

        try:
            # Check for Refusal first
            # We need to parse enough to know the rule and values for integrity check
            # but wait, calculator.parse does exactly that.
            temp_result = calculator.parse(dna_str)
            rule_name = temp_result['rule']
            values = temp_result['values']

            if integrity_manager.is_refusal(rule_name, values):
                log_observability(
                    correlation_id, actor_id, "process_dna", "REFUSAL",
                    idempotency_key=idempotency_key,
                    system_msg={
                        "refusal_reason": system_msgs.get("refusal_reason"),
                        "next_action_hint": system_msgs.get("next_action_hint")
                    }
                )
                # We do NOT add REFUSAL to the ledger so it can be retried after maintenance
                continue

            # Process Success
            entry = {
                'dna': dna_str,
                'rule': rule_name,
                'parsed': values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(rule_name, values)
            flat['dna'] = dna_str
            flat['rule'] = rule_name
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            # Apply Wear
            wear = integrity_manager.calculate_wear(rule_name, values)
            integrity_manager.apply_wear(wear)

            outcome = "SUCCESS"
            current_system_msg = None
            if wear < 0:
                current_system_msg = {"consequence_applied": system_msgs.get("consequence_applied")}

        except RuleParseError as e:
            outcome = "ERROR"
            print(f"[ERROR] RuleParseError for {dna_str}: {e}")
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

        latency_ms = int((time.time() - start_time) * 1000)

        # Update ledger
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        log_observability(
            correlation_id, actor_id, "process_dna", outcome,
            idempotency_key=idempotency_key,
            latency_ms=latency_ms,
            system_msg=current_system_msg if outcome == "SUCCESS" else None
        )
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_integrity = os.path.join(tmp_dir, 'integrity.json')

            try:
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

                # 4) Write Integrity State
                with open(tmp_integrity, 'w', encoding='utf-8') as inf:
                    json.dump({'integrity': integrity_manager.integrity}, inf)
                    inf.flush()
                    os.fsync(inf.fileno())

                # 5) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_integrity, integrity_path)

            except Exception as e:
                log_observability(correlation_id, actor_id, "persistence", "ERROR")
                raise PersistenceError("Failed to write output files atomically") from e

    log_observability(correlation_id, actor_id, "batch_end", "SUCCESS")
    print(f"[OK] Processed {new_processed_count} new DNA strings.")

if __name__ == '__main__':
    main()
