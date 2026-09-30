#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import tempfile
import shutil
from utils.dna_calculator import DNACalculator, RuleParseError

# UI Message Keys for Systemic Feedback
UI_CONSEQUENCE_APPLIED = "Heat Accumulation"
UI_REFUSAL_REASON = "Thermal Lockout"
UI_NEXT_ACTION_HINT = "Wait for dissipation. The system is indifferent to your deadlines."

# Mainframe Thermal System Constants
HEAT_PER_SEQUENCE = 2.0
LOCKOUT_THRESHOLD = 10.0
COOLING_RATE_PER_SEC = 0.5


class DNAStatus:
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"


class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass


class ThermalOverloadError(DNAProcessingError):
    """Raised when thermal lockout threshold is breached."""
    pass


class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass


class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass


class PersistenceError(DNAProcessingError):
    """Base class for persistence failures."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when ledger file exists but is corrupted."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when writing ledger file fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when atomic file persistence fails."""
    pass


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
    """
    Loads ledger file. Supports both structured format ({'ledger': {...}, 'system_state': {...}})
    and legacy flat dict format.
    Returns tuple: (ledger_dict, system_state_dict)
    """
    default_state = {
        'core_heat': 0.0,
        'last_processed_timestamp': None
    }
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Corrupted ledger file at {ledger_path}") from e

        if isinstance(data, dict):
            if 'ledger' in data:
                ledger = data.get('ledger', {})
                system_state = data.get('system_state', default_state)
                return ledger, system_state
            else:
                return data, default_state
        else:
            raise LedgerLoadError(f"Invalid ledger format at {ledger_path}")
    return {}, default_state


def save_ledger(ledger_path, ledger, system_state=None):
    """
    Saves ledger and system_state to ledger_path in structured format.
    """
    if system_state is None:
        system_state = {'core_heat': 0.0, 'last_processed_timestamp': None}

    structured = {
        'ledger': ledger,
        'system_state': system_state
    }
    try:
        tmp_ledger = ledger_path + ".tmp"
        with open(tmp_ledger, 'w', encoding='utf-8') as f:
            json.dump(structured, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_ledger, ledger_path)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e


def run_batch(correlation_id=None):
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

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        return

    ledger, system_state = load_ledger(ledger_path)
    initial_ledger = dict(ledger)

    # Core heat calculation and dissipation decay
    core_heat = float(system_state.get('core_heat', 0.0))
    last_time_str = system_state.get('last_processed_timestamp')

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_time_str:
        try:
            last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (now_dt - last_dt).total_seconds())
            dissipated_heat = elapsed_seconds * COOLING_RATE_PER_SEC
            core_heat = max(0.0, core_heat - dissipated_heat)
        except Exception:
            pass

    # 1) Load existing JSON output
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                content = json.load(jf)
                if isinstance(content, list):
                    parsed_json = content
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
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED) if isinstance(ledger[idempotency_key], dict) else DNAStatus.SKIPPED
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        # Check Thermal Fatigue / Overload invariant
        if core_heat + HEAT_PER_SEQUENCE > LOCKOUT_THRESHOLD:
            # Thermal Lockout triggered!
            # Save updated thermal state with initial_ledger to prevent partial inconsistent updates
            system_state['core_heat'] = core_heat
            system_state['last_processed_timestamp'] = now_iso
            save_ledger(ledger_path, initial_ledger, system_state)

            print(f"[{UI_CONSEQUENCE_APPLIED}] core_heat={core_heat:.1f} lockout_threshold={LOCKOUT_THRESHOLD:.1f}")
            raise ThermalOverloadError(
                f"[{UI_REFUSAL_REASON}] Heat level ({core_heat + HEAT_PER_SEQUENCE:.1f}) exceeds threshold ({LOCKOUT_THRESHOLD:.1f}). {UI_NEXT_ACTION_HINT}"
            )

        core_heat += HEAT_PER_SEQUENCE
        print(f"[{UI_CONSEQUENCE_APPLIED}] core_heat={core_heat:.1f}")

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
            terminal_outcome = DNAStatus.SUCCESS

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
            terminal_outcome = DNAStatus.ERROR

        ledger[idempotency_key] = {
            'terminal_outcome': terminal_outcome,
            'timestamp': now_iso
        }
        new_processed_count += 1

    system_state['core_heat'] = core_heat
    system_state['last_processed_timestamp'] = now_iso

    if new_processed_count > 0:
        # Save updated ledger & system state
        save_ledger(ledger_path, ledger, system_state)

        # Atomic write of output files
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
        print(f"     JSON -> {json_output_path}")
        print(f"     CSV  -> {csv_output_path}")
    else:
        # Save cooled state if needed
        save_ledger(ledger_path, ledger, system_state)
        print("[OK] No new DNA sequences to process.")


main = run_batch

if __name__ == '__main__':
    run_batch()
