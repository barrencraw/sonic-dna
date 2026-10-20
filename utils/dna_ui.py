#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import datetime
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input DNA sequence file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when ledger file loading fails due to corruption."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when ledger file saving fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic output file writing fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal lockout threshold is reached."""
    CONSEQUENCE_APPLIED = "Heat Accumulation"
    REFUSAL_REASON = "Thermal Lockout"
    NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

    def __init__(self, message=None):
        if not message:
            message = (
                f"Refusal Reason: {self.REFUSAL_REASON}. "
                f"Consequence: {self.CONSEQUENCE_APPLIED}. "
                f"Hint: {self.NEXT_ACTION_HINT}"
            )
        super().__init__(message)

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail):
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_entry = {
        "timestamp": now_utc,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name or "dna_batch_parser",
        "step": step,
        "outcome": str(outcome),
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_entry)}")

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

def parse_timestamp(ts_str):
    if not ts_str:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            dt = datetime.datetime.strptime(ts_str, fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except ValueError:
        return None

def load_ledger(ledger_path):
    current_time = datetime.datetime.now(datetime.timezone.utc)
    current_time_str = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger file: {ledger_path}") from e

        if isinstance(data, dict):
            if 'ledger' in data and 'system_state' in data:
                raw_ledger = data.get('ledger', {})
                system_state = data.get('system_state', {})
            else:
                raw_ledger = data
                system_state = {'core_heat': 0.0, 'last_processed_timestamp': current_time_str}
        else:
            raw_ledger = {}
            system_state = {'core_heat': 0.0, 'last_processed_timestamp': current_time_str}
    else:
        raw_ledger = {}
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': current_time_str}

    last_time_str = system_state.get('last_processed_timestamp')
    last_dt = parse_timestamp(last_time_str) if last_time_str else None
    if last_dt:
        elapsed_seconds = (current_time - last_dt).total_seconds()
        if elapsed_seconds > 0:
            decay = elapsed_seconds * 0.5
            current_heat = max(0.0, float(system_state.get('core_heat', 0.0)) - decay)
        else:
            current_heat = max(0.0, float(system_state.get('core_heat', 0.0)))
    else:
        current_heat = max(0.0, float(system_state.get('core_heat', 0.0)))

    system_state['core_heat'] = current_heat
    system_state['last_processed_timestamp'] = current_time_str

    return raw_ledger, system_state

def save_ledger(ledger_path, ledger, system_state):
    payload = {
        'ledger': ledger,
        'system_state': system_state
    }
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger file: {ledger_path}") from e

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    actor_id = "batch_parser"

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
                reader = cf.DictReader(cf) if hasattr(cf, 'fieldnames') else csv.DictReader(cf)
                if reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    csv_rows = list(reader)
        except Exception:
            pass

    new_processed_count = 0

    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        start_time = time.time()

        if idempotency_key in ledger:
            terminal_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS.value)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="deduplicate",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=(time.time() - start_time) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated entry with status {terminal_outcome}"
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Thermal Lockout Check
        if system_state.get('core_heat', 0.0) >= 10.0:
            # Core is overheated! Save initial_ledger so unwritten items are not falsely marked as processed
            save_ledger(ledger_path, initial_ledger, system_state)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="thermal_check",
                outcome=DNAStatus.REFUSED.value,
                latency_ms=(time.time() - start_time) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail=ThermalOverloadError.REFUSAL_REASON
            )
            raise ThermalOverloadError()

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
            system_state['core_heat'] = system_state.get('core_heat', 0.0) + 2.0
            system_state['last_processed_timestamp'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

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

        now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_str
        }

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parser",
            step="parse_sequence",
            outcome=outcome,
            latency_ms=(time.time() - start_time) * 1000,
            idempotency_key=idempotency_key,
            outcome_detail=f"Parsed with outcome {outcome}"
        )
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger, system_state)

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
    else:
        save_ledger(ledger_path, ledger, system_state)

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}")

main = run_batch

if __name__ == '__main__':
    main()
