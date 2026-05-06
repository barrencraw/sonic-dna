#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from utils.dna_calculator import DNACalculator, RuleParseError

class Outcome:
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if os.path.exists(input_path):
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

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    def __init__(self, current_heat):
        self.current_heat = current_heat
        self.REFUSAL_REASON = f"System core temperature at {current_heat:.2f} units. Thermal threshold exceeded."
        self.NEXT_ACTION_HINT = "Allow heat dissipation before further DNA sequencing."
        super().__init__(self.REFUSAL_REASON)

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

def log_observability(step, outcome, chain_name='dna_batch_chain', latency_ms=0, correlation_id=None):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    payload = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "actor_id": "sonic-dna-agent"
    }
    print(f"| TELEMETRY | {json.dumps(payload)}")
    return correlation_id

def main():
    start_time = time.time()
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')

    ensure_folder(raw_folder)
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

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    # Load heat and dissipate
    system_state = load_system_state(state_path)
    system_heat = system_state.get('system_heat', 0.0)
    system_heat = max(0.0, round(system_heat - 0.5, 2))

    correlation_id = log_observability("Batch Start", Outcome.START)

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        # Save dissipated heat even if no work
        system_state['system_heat'] = system_heat
        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(system_state, f, indent=2)
        log_observability("Batch End", Outcome.END, correlation_id=correlation_id)
        return

    ledger = load_ledger(ledger_path)

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

    new_processed_count = 0
    new_ledger_entries = {}

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger or idempotency_key in new_ledger_entries:
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True")
            log_observability("Idempotency", Outcome.SKIPPED, correlation_id=correlation_id)
            continue

        if system_heat >= 10.0:
            log_observability("DNA Processing", Outcome.ERROR, correlation_id=correlation_id)
            # Save heat state before raising
            system_state['system_heat'] = system_heat
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(system_state, f, indent=2)
            raise ThermalOverloadError(system_heat)

        try:
            result = calculator.parse(dna_str)
            consequence = None

            # Apply Fatigue consequences
            if result['rule'] == 'Volume':
                amp = result['values']['amp']
                system_heat = round(system_heat + (amp / 100.0), 2)
            elif result['rule'] == 'Clarity':
                heat_penalty = int(system_heat)
                if heat_penalty > 0:
                    result['values']['noise_floor']['value'] = max(0, result['values']['noise_floor']['value'] - heat_penalty)
                    result['values']['thd'] = min(1000, result['values']['thd'] + (heat_penalty * 10))
                    consequence = "Noise floor elevated, THD increased due to system heat."

            entry = {
                'dna': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            if consequence:
                entry['CONSEQUENCE_APPLIED'] = consequence

            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['rule'] = result['rule']
            if consequence:
                flat['CONSEQUENCE_APPLIED'] = consequence
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"{Outcome.ERROR}: {str(e)}"

        new_ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        new_processed_count += 1

    if new_processed_count > 0:
        ledger.update(new_ledger_entries)
        # ATOMIC WRITE PATTERN
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_state = os.path.join(tmp_dir, 'system_state.json')

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

                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                system_state['system_heat'] = system_heat
                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump(system_state, sf, indent=2)
                    sf.flush()
                    os.fsync(sf.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, state_path)

            except Exception as e:
                raise PersistenceError("Failed to write output files atomically") from e

    else:
        # Just update heat if no new DNA processed but dissipation happened
        system_state['system_heat'] = system_heat
        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(system_state, f, indent=2)

    latency = int((time.time() - start_time) * 1000)
    log_observability("Batch End", Outcome.END, latency_ms=latency, correlation_id=correlation_id)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
