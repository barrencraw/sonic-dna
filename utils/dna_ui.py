#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from utils.dna_calculator import DNACalculator, RuleParseError

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
    """Raised when system heat exceeds threshold."""
    pass

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA string.
    Returns a list of DNA strings (stripped, non-empty).
    """
    dna_list = []
    if not os.path.exists(input_path):
        return dna_list
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
            pass
    return {"system_heat": 0.0}

def save_system_state(state_path, state):
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def log_observability(correlation_id, chain_name, step, outcome, latency_ms=0, actor_id="system", idempotency_key=None):
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome.upper(),
        "latency_ms": latency_ms,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key
    }
    print(f"| TELEMETRY | {json.dumps(log_entry)}")

def main(data_dir=None):
    start_time = time.time()
    correlation_id = str(uuid.uuid4())

    # Determine file paths
    project_root = os.getcwd()
    if data_dir:
        data_folder = data_dir
    else:
        data_folder = os.path.join(project_root, 'data')

    raw_folder = os.path.join(data_folder, 'raw')
    output_folder = os.path.join(data_folder, 'output')
    ledger_path = os.path.join(data_folder, 'processed_ledger.json')
    state_path = os.path.join(data_folder, 'system_state.json')

    ensure_folder(output_folder)
    ensure_folder(raw_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')

    log_observability(correlation_id, "dna_batch_chain", "START", "SUCCESS")

    # Load system state and apply passive dissipation
    state = load_system_state(state_path)
    system_heat = state.get("system_heat", 0.0)
    system_heat = max(0.0, round(system_heat - 0.5, 2))
    state["system_heat"] = system_heat

    # Check for Thermal Overload
    if system_heat > 10.0:
        log_observability(correlation_id, "dna_batch_chain", "THERMAL_CHECK", "REFUSED",
                          idempotency_key="N/A")
        print(f"[CONSEQUENCE_APPLIED] Thermal stress detected. Heat: {system_heat}")
        print(f"[REFUSAL_REASON] Thermal overload (heat > 10.0). Processing suspended.")
        print(f"[NEXT_ACTION_HINT] Passive dissipation occurs over time. Reduce volume intensity to minimize heat gain.")
        # We still save the state (dissipation happened)
        save_system_state(state_path, state)
        raise ThermalOverloadError(f"Thermal overload: {system_heat}")

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_observability(correlation_id, "dna_batch_chain", "INIT", "ERROR")
        raise RuleLoadError(f"Could not load rules") from e

    # Read DNA strings
    dna_list = read_input_file(input_file)
    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        save_system_state(state_path, state)
        log_observability(correlation_id, "dna_batch_chain", "END", "SUCCESS",
                          latency_ms=int((time.time() - start_time) * 1000))
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
                if reader and reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    csv_rows = list(reader)
        except Exception:
            pass

    new_processed_count = 0
    new_ledger_entries = {}

    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in ledger or idempotency_key in new_ledger_entries:
            log_observability(correlation_id, "dna_batch_chain", "IDEMPOTENCY", "SKIPPED",
                              idempotency_key=idempotency_key)
            continue

        try:
            result = calculator.parse(dna_str)

            # Fatigue Logic: Heat Gain from Volume
            if result['rule'] == 'Volume':
                amp = result['values'].get('amp', 0)
                heat_gain = amp / 100.0
                system_heat = round(system_heat + heat_gain, 2)
                state["system_heat"] = system_heat

            # Fatigue Logic: Quality Penalty to Clarity
            if result['rule'] == 'Clarity':
                penalty = int(system_heat)
                if penalty > 0:
                    print(f"[CONSEQUENCE_APPLIED] Thermal stress detected. Clarity fidelity reduced. Penalty: {penalty}")
                    # Elevate noise floor (closer to 0)
                    if 'noise_floor' in result['values'] and 'value' in result['values']['noise_floor']:
                        nf = result['values']['noise_floor']['value']
                        result['values']['noise_floor']['value'] = max(0, nf - penalty)
                    # Increase THD
                    if 'thd' in result['values']:
                        thd = result['values']['thd']
                        result['values']['thd'] = min(1000, thd + penalty * 10)

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
            outcome = "success"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        new_ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        log_observability(correlation_id, "dna_batch_chain", "IDEMPOTENCY", outcome,
                          idempotency_key=idempotency_key)
        new_processed_count += 1

    if new_processed_count > 0:
        ledger.update(new_ledger_entries)

        # ATOMIC WRITE PATTERN
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')
            tmp_ledger = os.path.join(tmp_dir, 'ledger.json')

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

                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)

            except Exception as e:
                log_observability(correlation_id, "dna_batch_chain", "PERSISTENCE", "ERROR")
                raise PersistenceError("Failed to write output files atomically") from e

    # Always save system state (even if no new DNA processed, for dissipation)
    save_system_state(state_path, state)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    log_observability(correlation_id, "dna_batch_chain", "END", "SUCCESS",
                      latency_ms=int((time.time() - start_time) * 1000))

if __name__ == '__main__':
    main()
