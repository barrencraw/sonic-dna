#!/usr/bin/env python3
import os
import json
import csv
import time
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
    """Raised when system heat exceeds safe limits."""
    def __init__(self, current_heat):
        self.current_heat = current_heat
        self.message = (
            f"Core temperature at {current_heat:.2f}U. Safety interlock engaged."
        )
        super().__init__(self.message)
        self.refusal_reason = f"CRITICAL_THERMAL_EXCESS: {current_heat:.2f}U"
        self.next_action_hint = "ALLOW_HEAT_DISSIPATION_BY_IDLE_CYCLES"

def log_observability(step, outcome, correlation_id="system", chain_name="dna_batch_chain", latency_ms=0, actor_id="system"):
    """
    Standardized telemetry logger.
    Grep Recipe: grep "| TELEMETRY |" <log_file> | jq '.data'
    """
    payload = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.value if isinstance(outcome, Outcome) else outcome,
        "latency_ms": latency_ms,
        "actor_id": actor_id
    }
    print(f"| TELEMETRY | {json.dumps(payload)}")

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

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def main(data_dir=None):
    start_time = time.time()
    log_observability("Batch Start", Outcome.START)

    # Determine file paths
    project_root = os.getcwd()
    data_root = data_dir if data_dir else os.path.join(project_root, 'data')
    raw_folder = os.path.join(data_root, 'raw')
    output_folder = os.path.join(data_root, 'output')
    ledger_path = os.path.join(data_root, 'processed_ledger.json')
    state_path = os.path.join(data_root, 'system_state.json')

    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_observability("Batch End", Outcome.SKIPPED)
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability("Rule Loading", Outcome.ERROR)
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_observability("Input Reading", Outcome.ERROR)
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        log_observability("Batch End", Outcome.SKIPPED)
        return

    ledger = load_json(ledger_path)
    state = load_json(state_path)

    system_heat = state.get('system_heat', 0.0)
    # Passive dissipation: 0.5 units per session start
    system_heat = max(0.0, system_heat - 0.5)

    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        parsed_json = load_json(json_output_path)
        if not isinstance(parsed_json, list):
            parsed_json = []

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

    try:
        for dna_str in dna_list:
            if dna_str in ledger or dna_str in new_ledger_entries:
                log_observability("Idempotency Check", Outcome.SKIPPED, correlation_id=dna_str)
                continue

            # Thermal overload check
            if system_heat > 10.0:
                err = ThermalOverloadError(system_heat)
                print(f"[CONSEQUENCE_APPLIED] Fatigue penalty: processing halted.")
                print(f"[REFUSAL_REASON] {err.refusal_reason}")
                print(f"[NEXT_ACTION_HINT] {err.next_action_hint}")
                raise err

            try:
                result = calculator.parse(dna_str)

                # Tradeoff logic
                if result['rule'] == 'Volume':
                    # Increase heat
                    amp = result['values'].get('amp', 0)
                    heat_gain = amp / 100.0
                    system_heat += heat_gain
                    print(f"[CONSEQUENCE_APPLIED] Volume processing heat gain: +{heat_gain:.2f}U (Total: {system_heat:.2f}U)")

                elif result['rule'] == 'Clarity':
                    # Apply heat penalties
                    if system_heat >= 1.0:
                        penalty = int(system_heat)
                        # Noise floor: N090 becomes N085 if heat=5 (lowering dB magnitude = raising noise)
                        if 'noise_floor' in result['values']:
                            orig_noise = result['values']['noise_floor']['value']
                            result['values']['noise_floor']['value'] = max(0, orig_noise - penalty)

                        # THD: increase by 10 per heat unit
                        if 'thd' in result['values']:
                            orig_thd = result['values']['thd']
                            result['values']['thd'] = min(1000, orig_thd + (penalty * 10))

                        print(f"[CONSEQUENCE_APPLIED] Thermal interference applied to Clarity DNA. Noise floor shift: -{penalty}dB, THD increase: +{penalty*10}")

                entry = {
                    'dna': dna_str,
                    'rule': result['rule'],
                    'parsed': result['values']
                }
                parsed_json.append(entry)

                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_str
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = Outcome.SUCCESS

            except RuleParseError as e:
                parsed_json.append({'dna': dna_str, 'error': str(e)})
                flat = {'dna': dna_str, 'error': str(e)}
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = Outcome.ERROR

            new_ledger_entries[dna_str] = {
                'terminal_outcome': outcome.value,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            log_observability("Item Processed", outcome, correlation_id=dna_str)
            new_processed_count += 1

    except ThermalOverloadError as toe:
        # We stop processing but keep what we've done so far
        pass

    if new_processed_count > 0:
        # Atomic commit
        ledger.update(new_ledger_entries)
        state['system_heat'] = system_heat

        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')
            tmp_state = os.path.join(tmp_dir, 'state.json')

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

                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump(state, sf, indent=2)
                    sf.flush()
                    os.fsync(sf.fileno())

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, state_path)

            except Exception as e:
                log_observability("Commit", Outcome.ERROR)
                raise PersistenceError("Failed to write output files atomically") from e

    latency = int((time.time() - start_time) * 1000)
    log_observability("Batch End", Outcome.END, latency_ms=latency)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
