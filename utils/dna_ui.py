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

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading ledger fails due to corruption."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file persistence fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when core heat exceeds threshold."""
    pass

# Message Keys for Systemic Feedback
MSG_CONSEQUENCE = "Heat Accumulation"
MSG_REFUSAL_REASON = "Thermal Lockout"
MSG_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

def log_structured(correlation_id=None, actor_id="batch_parser", chain_name="dna_batch_parser",
                   step="parse_sequence", outcome="success", latency_ms=0.0,
                   idempotency_key="", outcome_detail=""):
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")

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
    if not os.path.exists(ledger_path):
        return {"ledger": {}, "system_state": {"core_heat": 0.0, "last_processed_timestamp": ""}}
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise LedgerLoadError(f"Corrupted ledger format in {ledger_path}")
            if "ledger" in data and isinstance(data["ledger"], dict):
                system_state = data.get("system_state", {})
                if not isinstance(system_state, dict):
                    system_state = {}
                return {
                    "ledger": data["ledger"],
                    "system_state": {
                        "core_heat": float(system_state.get("core_heat", 0.0)),
                        "last_processed_timestamp": str(system_state.get("last_processed_timestamp", ""))
                    }
                }
            else:
                return {
                    "ledger": data,
                    "system_state": {
                        "core_heat": 0.0,
                        "last_processed_timestamp": ""
                    }
                }
    except json.JSONDecodeError as e:
        raise LedgerLoadError(f"Corrupted ledger JSON file at {ledger_path}") from e
    except Exception as e:
        if isinstance(e, PersistenceError):
            raise
        raise LedgerLoadError(f"Failed to load ledger: {str(e)}") from e

def save_ledger(ledger_path, ledger_data):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger file: {ledger_path}") from e

def commit_outputs_and_ledger(output_folder, json_output_path, csv_output_path, ledger_path,
                             parsed_json, csv_rows, all_flattened_keys, ledger_data, write_outputs=True):
    if write_outputs:
        try:
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

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

    save_ledger(ledger_path, ledger_data)

def run_batch(correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')

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

    ledger_data = load_ledger(ledger_path)
    ledger = ledger_data["ledger"]
    system_state = ledger_data["system_state"]

    # Calculate thermal cooling
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    last_time_str = system_state.get("last_processed_timestamp", "")
    current_heat = system_state.get("core_heat", 0.0)

    if last_time_str:
        try:
            last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_sec = max(0.0, (now_dt - last_dt).total_seconds())
            current_heat = max(0.0, current_heat - (elapsed_sec * 0.5))
        except Exception:
            pass

    # Load existing JSON output if present
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                parsed_json = json.load(jf)
                if not isinstance(parsed_json, list):
                    parsed_json = []
        except Exception:
            parsed_json = []

    # Load existing CSV output if present
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
    thermal_lockout_triggered = False

    for dna_seq in dna_sequence_list:
        idempotency_key = dna_seq
        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS.value)
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(
                correlation_id=correlation_id,
                step="deduplicate_check",
                outcome=DNAStatus.SKIPPED.value,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated (already processed with outcome '{term_outcome}')"
            )
            continue

        # Thermal lockout check before processing new sequence
        if current_heat + 2.0 > 10.0:
            thermal_lockout_triggered = True
            log_structured(
                correlation_id=correlation_id,
                step="thermal_check",
                outcome=DNAStatus.REFUSED.value,
                idempotency_key=idempotency_key,
                outcome_detail=f"{MSG_REFUSAL_REASON}: core heat {current_heat:.1f}. {MSG_CONSEQUENCE}. {MSG_NEXT_ACTION_HINT}"
            )
            break

        start_time = time.time()
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

        latency_ms = (time.time() - start_time) * 1000.0
        current_heat += 2.0
        last_processed_timestamp = now_iso

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            step="parse_sequence",
            outcome=outcome,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
            outcome_detail=f"Processed sequence with outcome {outcome}. {MSG_CONSEQUENCE}: +2.0 heat (current: {current_heat:.1f})"
        )

    # Save system state
    system_state["core_heat"] = current_heat
    system_state["last_processed_timestamp"] = now_iso

    ledger_data["ledger"] = ledger
    ledger_data["system_state"] = system_state

    # Save outputs & ledger
    commit_outputs_and_ledger(
        output_folder=output_folder,
        json_output_path=json_output_path,
        csv_output_path=csv_output_path,
        ledger_path=ledger_path,
        parsed_json=parsed_json,
        csv_rows=csv_rows,
        all_flattened_keys=all_flattened_keys,
        ledger_data=ledger_data,
        write_outputs=(new_processed_count > 0)
    )

    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}. Core heat: {current_heat:.1f}")

    if thermal_lockout_triggered:
        raise ThermalOverloadError(
            f"{MSG_REFUSAL_REASON}: Heat limit exceeded (Core heat: {current_heat:.1f}/10.0). {MSG_CONSEQUENCE}. {MSG_NEXT_ACTION_HINT}"
        )

main = run_batch

if __name__ == '__main__':
    main()
