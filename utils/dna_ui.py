#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
import datetime
from datetime import timezone
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input sequence file fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing ledger file fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger file fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system heat exceeds thermal safety lockout threshold."""
    def __init__(self, message="Heat Accumulation: Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines."):
        super().__init__(message)
        self.consequence_applied = "Heat Accumulation"
        self.refusal_reason = "Thermal Lockout"
        self.next_action_hint = "Wait for dissipation. The system is indifferent to your deadlines."

class DNAStatus:
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail=None):
    now_str = datetime.datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_payload = {
        'timestamp': now_str,
        'correlation_id': correlation_id,
        'actor_id': actor_id,
        'chain_name': chain_name,
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail or {}
    }
    print(f"JSON_LOG:{json.dumps(log_payload)}")

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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger at {ledger_path}: {e}") from e

        if isinstance(data, dict):
            if 'ledger' in data:
                ledger = data.get('ledger', {})
                system_state = data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})
                return ledger, system_state
            else:
                # Legacy flat layout
                return data, {'core_heat': 0.0, 'last_processed_timestamp': None}
        else:
            raise LedgerLoadError(f"Corrupted ledger structure at {ledger_path}")
    return {}, {'core_heat': 0.0, 'last_processed_timestamp': None}

def save_ledger(ledger_path, ledger, system_state):
    try:
        data = {
            'ledger': ledger,
            'system_state': system_state
        }
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e

def run_batch(correlation_id=None, actor_id='batch_parser'):
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

    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger, system_state = load_ledger(ledger_path)

    now_utc = datetime.datetime.now(timezone.utc)
    now_iso = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Apply thermal decay
    core_heat = float(system_state.get('core_heat', 0.0))
    last_ts_str = system_state.get('last_processed_timestamp')
    if last_ts_str:
        try:
            last_dt = datetime.datetime.strptime(last_ts_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            elapsed_seconds = max(0.0, (now_utc - last_dt).total_seconds())
            core_heat = max(0.0, core_heat - (elapsed_seconds * 0.5))
        except Exception:
            pass

    system_state['core_heat'] = core_heat

    # Initial lockout check
    if core_heat >= 10.0:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name='dna_batch_parser',
            step='thermal_check',
            outcome=DNAStatus.REFUSED,
            latency_ms=0,
            idempotency_key='system_core_heat',
            outcome_detail={'reason': 'Thermal Lockout', 'heat': core_heat}
        )
        raise ThermalOverloadError("Heat Accumulation: Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines.")

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
    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger:
            terminal = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal}")
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name='dna_batch_parser',
                step='process_sequence',
                outcome=DNAStatus.SKIPPED,
                latency_ms=0,
                idempotency_key=idempotency_key,
                outcome_detail={'dedupe_hit': True, 'terminal_outcome': terminal}
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        if core_heat >= 10.0:
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name='dna_batch_parser',
                step='process_sequence',
                outcome=DNAStatus.REFUSED,
                latency_ms=0,
                idempotency_key=idempotency_key,
                outcome_detail={'reason': 'Thermal Lockout', 'heat': core_heat}
            )
            raise ThermalOverloadError("Heat Accumulation: Thermal Lockout. Wait for dissipation. The system is indifferent to your deadlines.")

        start_time = time.time()
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
            core_heat += 2.0

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

        latency_ms = int((time.time() - start_time) * 1000)
        now_ts = datetime.datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = now_ts

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_ts
        }
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name='dna_batch_parser',
            step='process_sequence',
            outcome=outcome,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
            outcome_detail={'heat': core_heat}
        )

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger, system_state)

        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    main()
