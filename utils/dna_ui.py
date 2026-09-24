#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input file cannot be read."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when reading ledger file fails or JSON is corrupted."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic output file write fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when mainframe core heat exceeds safety lockout threshold."""
    def __init__(self, message, consequence_applied="Heat Accumulation", refusal_reason="Thermal Lockout", next_action_hint="Wait for dissipation. The system is indifferent to your deadlines."):
        super().__init__(message)
        self.consequence_applied = consequence_applied
        self.refusal_reason = refusal_reason
        self.next_action_hint = next_action_hint

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
                if isinstance(data, dict) and 'ledger' in data and 'system_state' in data:
                    return data['ledger'], data.get('system_state', {'core_heat': 0.0, 'last_processed_timestamp': None})
                elif isinstance(data, dict):
                    return data, {'core_heat': 0.0, 'last_processed_timestamp': None}
                else:
                    return {}, {'core_heat': 0.0, 'last_processed_timestamp': None}
        except json.JSONDecodeError as e:
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}") from e
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}, {'core_heat': 0.0, 'last_processed_timestamp': None}

def save_ledger(ledger_path, ledger, system_state):
    try:
        payload = {
            'ledger': ledger,
            'system_state': system_state
        }
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def log_structured(timestamp, correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    log_entry = {
        'timestamp': timestamp,
        'correlation_id': correlation_id,
        'actor_id': actor_id,
        'chain_name': chain_name,
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_entry)}")

def run_batch(correlation_id=None, actor_id='batch_parser'):
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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
    initial_ledger = dict(ledger)

    current_time = datetime.datetime.now(datetime.timezone.utc)
    current_time_str = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Thermal Decay Calculation
    last_time_str = system_state.get('last_processed_timestamp')
    core_heat = float(system_state.get('core_heat', 0.0))
    if last_time_str:
        try:
            if 'T' in last_time_str:
                last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            else:
                last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc)
            elapsed = (current_time - last_time).total_seconds()
            if elapsed > 0:
                decay = elapsed * 0.5
                core_heat = max(0.0, core_heat - decay)
        except Exception:
            pass

    # Count new sequences to process
    new_sequences = [seq for seq in dna_sequence_list if seq not in ledger]
    additional_heat = len(new_sequences) * 2.0
    projected_heat = core_heat + additional_heat

    if projected_heat > 10.0:
        system_state['core_heat'] = core_heat
        system_state['last_processed_timestamp'] = current_time_str
        save_ledger(ledger_path, initial_ledger, system_state)
        raise ThermalOverloadError(
            f"Mainframe thermal lockout: core heat {projected_heat:.1f} exceeds threshold 10.0.",
            consequence_applied="Heat Accumulation",
            refusal_reason="Thermal Lockout",
            next_action_hint="Wait for dissipation. The system is indifferent to your deadlines."
        )

    # 1) Load existing JSON output
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
            term_outcome = ledger[idempotency_key].get('terminal_outcome', 'success')
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

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
            outcome = "success"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_seq,
                'dna_sequence': dna_seq,
                'error': str(e)
            })
            flat = {'dna': dna_seq, 'dna_sequence': dna_seq, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        ledger[idempotency_key] = {
            'terminal_outcome': 'success' if outcome == 'success' else 'error',
            'timestamp': current_time_str
        }
        core_heat += 2.0
        new_processed_count += 1
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")

    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = current_time_str
    save_ledger(ledger_path, ledger, system_state)

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
                raise PersistenceError("Failed to write output files atomically") from e

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    main()
