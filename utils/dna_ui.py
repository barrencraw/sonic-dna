#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
import shutil
import uuid
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError, ParsedDNA

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

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system heat exceeds the safety threshold (10.0)."""
    pass

# Systemic Message Keys
CONSEQUENCE_APPLIED = "CONSEQUENCE_APPLIED"
REFUSAL_REASON = "REFUSAL_REASON"
NEXT_ACTION_HINT = "NEXT_ACTION_HINT"

class Outcome(Enum):
    START = "START"
    END = "END"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"

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

def log_observability(message, data=None, actor_id='system', correlation_id=None):
    """
    Standardized pipe-delimited telemetry format.
    | TELEMETRY | {"message": "...", "data": {...}, "actor_id": "...", "timestamp": "...", "correlation_id": "..."}
    """
    payload = {
        "message": message,
        "data": data or {},
        "actor_id": actor_id,
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "correlation_id": correlation_id
    }
    print(f"| TELEMETRY | {json.dumps(payload)}")

def main():
    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    state_path = os.path.join(project_root, 'data', 'system_state.json')
    ensure_folder(output_folder)

    correlation_id = str(uuid.uuid4())
    log_observability("[Batch Start]", {"correlation_id": correlation_id}, correlation_id=correlation_id)

    # Load and Dissipate Heat
    state = load_system_state(state_path)
    system_heat = state.get("system_heat", 0.0)
    system_heat = max(0.0, system_heat - 0.5)  # Passive dissipation
    state["system_heat"] = system_heat
    save_system_state(state_path, state)

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

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
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
            outcome_val = ledger.get(idempotency_key, new_ledger_entries.get(idempotency_key))['terminal_outcome']
            log_observability("[Idempotency]", {"key": idempotency_key, "dedupe_hit": True, "terminal_outcome": outcome_val}, correlation_id=correlation_id)
            continue

        log_observability("[Idempotency]", {"key": idempotency_key, "dedupe_hit": False, "terminal_outcome": "processing"}, correlation_id=correlation_id)

        try:
            # FATIGUE SYSTEM: Thermal Overload Refusal for Clarity
            if dna_str.startswith("CLA") and system_heat > 10.0:
                raise ThermalOverloadError(json.dumps({
                    REFUSAL_REASON: f"Core temperature critical ({system_heat:.1f}). Clarity processing offline.",
                    NEXT_ACTION_HINT: "Allow heat dissipation before retrying CLA sequence."
                }))

            result: ParsedDNA = calculator.parse(dna_str)

            # FATIGUE SYSTEM: Consequences for Clarity
            if result.rule == "Clarity":
                heat_int = int(system_heat)
                if heat_int > 0:
                    # Noise Floor elevation
                    orig_nf = result.values['noise_floor']['value']
                    result.values['noise_floor']['value'] = max(0, orig_nf - heat_int)
                    # THD increase (1 heat = 0.10% THD = 10 units)
                    orig_thd = result.values['thd']
                    result.values['thd'] = min(1000, orig_thd + (heat_int * 10))

                    log_observability("Consequence applied", {
                        "rule": "Clarity",
                        "system_heat": system_heat,
                        CONSEQUENCE_APPLIED: f"Thermal noise penalty: -{heat_int}dB floor, +{heat_int*10} THD units."
                    }, correlation_id=correlation_id)

            entry = {
                'dna': dna_str,
                'rule': result.rule,
                'parsed': result.values
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result.rule, result.values)
            flat['dna'] = dna_str
            flat['rule'] = result.rule
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.SUCCESS.name

            # FATIGUE SYSTEM: Heat Gain from Volume
            if result.rule == "Volume":
                try:
                    amp = int(dna_str[3:7])
                    heat_gain = amp / 100.0
                    system_heat += heat_gain
                    state["system_heat"] = system_heat
                    log_observability("Heat gain applied", {
                        "rule": "Volume",
                        "heat_gain": heat_gain,
                        "total_heat": system_heat
                    }, correlation_id=correlation_id)
                except (ValueError, IndexError):
                    pass

        except ThermalOverloadError as e:
            outcome = Outcome.SKIPPED.name
            log_observability("DNA processing refused", {
                "dna": dna_str,
                "error": str(e)
            }, correlation_id=correlation_id)
        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = Outcome.ERROR.name

        new_ledger_entries[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

    if new_processed_count > 0:
        ledger.update(new_ledger_entries)

        # ATOMIC WRITE PATTERN (includes ledger and system state)
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'toSequence_parsed.json')
            tmp_csv = os.path.join(tmp_dir, 'toSequence_parsed.csv')
            tmp_ledger = os.path.join(tmp_dir, 'processed_ledger.json')
            tmp_state = os.path.join(tmp_dir, 'system_state.json')

            try:
                # 1) Write JSON
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) Write CSV
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Write Ledger
                with open(tmp_ledger, 'w', encoding='utf-8') as lf:
                    json.dump(ledger, lf, indent=2)
                    lf.flush()
                    os.fsync(lf.fileno())

                # 4) Write System State
                with open(tmp_state, 'w', encoding='utf-8') as sf:
                    json.dump(state, sf, indent=2)
                    sf.flush()
                    os.fsync(sf.fileno())

                # Commit
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)
                os.replace(tmp_ledger, ledger_path)
                os.replace(tmp_state, state_path)

            except Exception as e:
                raise PersistenceError("Failed to commit batch results atomically") from e

    log_observability("[Terminal Outcome]", {
        "new_processed": new_processed_count,
        "total_ledger": len(ledger),
        "system_heat": system_heat
    }, correlation_id=correlation_id)

    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")

if __name__ == '__main__':
    main()
