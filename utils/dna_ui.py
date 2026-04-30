#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    PROCESSING = "PROCESSING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    NO_NEW_DNA = "NO_NEW_DNA"

def log_observability(outcome, chain_name="dna_batch_chain", step="processing", extra=None, correlation_id=None):
    """
    Structured pipe-delimited telemetry for high searchability.
    Format: | TELEMETRY | {json_payload}
    """
    payload = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id or "N/A",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "actor_id": "system"
    }
    if extra:
        payload.update(extra)

    print(f"| TELEMETRY | {json.dumps(payload)}")

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_list.append(s)
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

class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when the core temperature is too high to process Clarity DNA."""
    def __init__(self, heat):
        self.heat = heat
        self.message = f"Core temperature at {heat:.1f}U. Clarity DNA processing refused."
        super().__init__(self.message)

    @property
    def refusal_reason(self):
        return self.message

    @property
    def next_action_hint(self):
        return "Allow heat dissipation. Cease high-amplitude Volume processing."

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass
def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ledger(ledger_path, ledger):
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2)

def load_system_state(state_path):
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"system_heat": 0.0}
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    correlation_id = str(uuid.uuid4())
    log_observability(Outcome.START, step="batch_init", correlation_id=correlation_id)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability(Outcome.NO_NEW_DNA, step="batch_init", correlation_id=correlation_id, extra={"reason": "input_not_found"})
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(Outcome.ERROR, step="calculator_init", correlation_id=correlation_id, extra={"error": str(e)})
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability(Outcome.ERROR, step="read_input", correlation_id=correlation_id, extra={"error": str(e)})
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability(Outcome.NO_NEW_DNA, step="batch_init", correlation_id=correlation_id)
        return

    ledger = load_ledger(ledger_path)
    system_state = load_system_state(state_path)
    system_heat = system_state.get("system_heat", 0.0)

    # Natural cooling: -1.0 per batch
    system_heat = max(0.0, system_heat - 1.0)
    log_observability(Outcome.PROCESSING, step="cooling", correlation_id=correlation_id, extra={"system_heat": system_heat})

    # 1) Load existing JSON output
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

    # 2) Load existing CSV rows
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

    from utils.dna_calculator import RuleParseError

    new_processed_count = 0
    errors_count = 0
    new_ledger_entries = {}

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger or idempotency_key in new_ledger_entries:
            log_observability(Outcome.SKIPPED, step="idempotency_check", correlation_id=correlation_id, extra={"dna": dna_str})
            continue

        log_observability(Outcome.PROCESSING, step="parse_start", correlation_id=correlation_id, extra={"dna": dna_str})

        try:
            # 1. Thermal Refusal
            if dna_str.startswith("CLA") and system_heat > 10.0:
                raise ThermalOverloadError(system_heat)

            # 2. Parse DNA
            result = calculator.parse(dna_str)

            # 3. Apply Penalties
            if result['rule'] == 'Clarity' and system_heat > 0.0:
                # noise_floor: N090 -> N085 if heat is 5
                orig_noise = result['values']['noise_floor']['value']
                result['values']['noise_floor']['value'] = max(0, orig_noise - int(system_heat))

                # thd: 0.10% increase per heat unit
                orig_thd = result['values']['thd']
                result['values']['thd'] = min(1000, orig_thd + (int(system_heat) * 10))

                log_observability(Outcome.SUCCESS, step="penalty_applied", correlation_id=correlation_id,
                                  extra={"dna": dna_str, "CONSEQUENCE_APPLIED": "Clarity degradation due to core temperature."})

            # 4. Heat Accumulation
            if result['rule'] == 'Volume':
                # VOL0890... -> 0890 / 100.0 = 8.9 heat
                amp = result['values']['amp']
                heat_gain = amp / 100.0
                system_heat += heat_gain
                log_observability(Outcome.SUCCESS, step="heat_gain", correlation_id=correlation_id,
                                  extra={"dna": dna_str, "gain": heat_gain, "total_heat": system_heat})

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS

        except ThermalOverloadError as e:
            log_observability(Outcome.ERROR, step="thermal_refusal", correlation_id=correlation_id,
                              extra={"dna": dna_str, "REFUSAL_REASON": e.refusal_reason, "NEXT_ACTION_HINT": e.next_action_hint})
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR
            errors_count += 1

        except RuleParseError as e:
            log_observability(Outcome.ERROR, step="parse_error", correlation_id=correlation_id, extra={"dna": dna_str, "error": str(e)})
            parsed_json.append({'dna': dna_str, 'error': str(e)})
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR
            errors_count += 1

        new_ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome.value,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    # ATOMIC WRITE PATTERN:
    if new_processed_count > 0:
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_state = os.path.join(tmp_dir, 'state.json')

            try:
                # 1) JSON
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Ledger
                ledger.update(new_ledger_entries)
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) System State
                system_state["system_heat"] = system_heat
                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump(system_state, sf, indent=2)
                    sf.flush()
                    os.fsync(sf.fileno())

                # Commit
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, state_path)

            except Exception as e:
                log_observability(Outcome.ERROR, step="atomic_commit", correlation_id=correlation_id, extra={"error": str(e)})
                raise PersistenceError("Failed to write output files atomically") from e

    # Final Outcome
    batch_outcome = Outcome.SUCCESS
    if new_processed_count == 0:
        batch_outcome = Outcome.NO_NEW_DNA
    elif errors_count > 0:
        batch_outcome = Outcome.PARTIAL_SUCCESS if errors_count < new_processed_count else Outcome.ERROR

    log_observability(batch_outcome, step="batch_end", correlation_id=correlation_id,
                      extra={"processed": new_processed_count, "errors": errors_count, "system_heat": system_heat})

if __name__ == '__main__':
    main()
