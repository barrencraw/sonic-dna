#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import uuid
import datetime
from utils.dna_calculator import DNACalculator, RuleParseError
from utils.integrity_manager import IntegrityManager

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    dna_list = []
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
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "chain": "dna_batch_chain",
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "step": step,
        "outcome": outcome,
        "idempotency_key": idempotency_key,
        "latency_ms": latency_ms,
        "system_msg": system_msg
    }
    print(f"[OBSERVABILITY] {json.dumps(log_entry)}")

def main(correlation_id=None, actor_id='once_runner'):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    integrity_path = os.path.join(project_root, 'data', 'system_integrity.json')
    messages_path = os.path.join(project_root, 'data', 'system_messages.json')

    ensure_folder(output_folder)
    ensure_folder(os.path.dirname(ledger_path))

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(correlation_id, actor_id, "init", "NO_NEW_DATA")
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, actor_id, "init", "ERROR: RuleLoadError")
        raise RuleLoadError(f"Could not load rules") from e

    integrity_manager = IntegrityManager(integrity_path)
    current_integrity = integrity_manager.integrity

    system_messages = {}
    if os.path.exists(messages_path):
        with open(messages_path, 'r', encoding='utf-8') as f:
            system_messages = json.load(f)

    dna_list = read_input_file(input_file)
    if not dna_list:
        log_observability(correlation_id, actor_id, "init", "NO_NEW_DATA")
        return

    ledger = load_ledger(ledger_path)
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as f:
                parsed_json = json.load(f)
        except Exception: pass

    csv_rows = []
    all_flattened_keys = set()
    if os.path.exists(csv_output_path):
        try:
            with open(csv_output_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    csv_rows = list(reader)
        except Exception: pass

    log_observability(correlation_id, actor_id, "start", "SUCCESS")

    new_processed = 0
    for dna_str in dna_list:
        start_time = time.time()
        if dna_str in ledger:
            log_observability(correlation_id, actor_id, "process_dna", "DEDUPE", dna_str)
            continue

        try:
            # Preliminary parse for integrity check
            parse_result = calculator.parse(dna_str)

            if integrity_manager.is_refusal(current_integrity, parse_result):
                msg = system_messages.get('refusal_reason', "Refusal") + " " + system_messages.get('next_action_hint', "")
                log_observability(correlation_id, actor_id, "process_dna", "REFUSAL", dna_str, system_msg=msg)
                continue

            # Update tracked integrity
            current_integrity = integrity_manager.calculate_new_integrity(current_integrity, parse_result)

            # Process
            entry = {'dna': dna_str, 'rule': parse_result['rule'], 'parsed': parse_result['values']}
            parsed_json.append(entry)

            flat = flatten_parsed(parse_result['rule'], parse_result['values'])
            flat['dna'] = dna_str
            flat['rule'] = parse_result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = "SUCCESS"
            sys_msg = system_messages.get('consequence_applied', "").format(integrity=current_integrity)

        except RuleParseError as e:
            outcome = f"ERROR: {str(e)}"
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            sys_msg = "Rule violation recorded."

        latency = int((time.time() - start_time) * 1000)
        ledger[dna_str] = {'terminal_outcome': outcome, 'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}
        log_observability(correlation_id, actor_id, "process_dna", outcome, dna_str, latency, sys_msg)
        new_processed += 1

    # Atomic Commit
    if new_processed > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_integrity = os.path.join(tmp_dir, 'integrity.json')

            try:
                with open(tmp_json, 'w', encoding='utf-8') as f:
                    json.dump(parsed_json, f, indent=2)
                    f.flush(); os.fsync(f.fileno())

                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        writer.writerow({k: row.get(k, '') for k in fieldnames})
                    f.flush(); os.fsync(f.fileno())

                with open(tmp_ledger, 'w', encoding='utf-8') as f:
                    json.dump(ledger, f, indent=2)
                    f.flush(); os.fsync(f.fileno())

                with open(tmp_integrity, 'w', encoding='utf-8') as f:
                    json.dump({'integrity': current_integrity}, f)
                    f.flush(); os.fsync(f.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_integrity, integrity_path)
            except Exception as e:
                log_observability(correlation_id, actor_id, "commit", "ERROR: PersistenceError")
                raise PersistenceError("Failed to write outputs") from e

    log_observability(correlation_id, actor_id, "batch_complete", "SUCCESS")

if __name__ == '__main__':
    main()
