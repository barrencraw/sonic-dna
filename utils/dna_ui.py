#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import datetime
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# --- ENUM & EXCEPTION TAXONOMY ---

class DNAStatus:
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

    @property
    def success(self):
        return self.SUCCESS

    @property
    def error(self):
        return self.ERROR

    @property
    def skipped(self):
        return self.SKIPPED

    @property
    def refused(self):
        return self.REFUSED

class DNAProcessingError(Exception):
    """Base exception for all DNA processing failures."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rule files cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when input files cannot be read."""
    pass

class ThermalOverloadError(DNAProcessingError):
    """Raised when system thermal lockout threshold is reached."""
    pass

class PersistenceError(DNAProcessingError):
    """Base exception for storage failures."""
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


# --- STRUCTURED LOGGING HYGIENE ---

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key=None, outcome_detail=None):
    """
    Emits standardized structured telemetry JSON log prefixed with JSON_LOG:
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_payload = {
        "timestamp": now_utc,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name or "dna_batch_parser",
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_payload)}")


# --- HELPER FUNCTIONS ---

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
        return dna_sequence_list
    except Exception as e:
        raise InputReadError(f"Failed to read input file '{input_path}': {e}") from e

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
    Loads ledger file. Supports both structured format ({'ledger': {}, 'system_state': {}})
    and legacy flat dict format ({'key': {'terminal_outcome': '...'}}).
    Raises LedgerLoadError if file exists but contains invalid JSON.
    """
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "ledger" in data and isinstance(data["ledger"], dict):
                        return data
                    else:
                        # Convert legacy flat format to structured format
                        return {
                            "ledger": data,
                            "system_state": {
                                "core_heat": 0.0,
                                "last_processed_timestamp": None
                            }
                        }
                return {"ledger": {}, "system_state": {"core_heat": 0.0, "last_processed_timestamp": None}}
        except Exception as e:
            raise LedgerLoadError(f"Failed to load processed ledger from '{ledger_path}': {e}") from e
    return {"ledger": {}, "system_state": {"core_heat": 0.0, "last_processed_timestamp": None}}

def save_ledger(ledger_path, ledger_data):
    """
    Saves ledger_data to ledger_path cleanly.
    """
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save processed ledger to '{ledger_path}': {e}") from e


# --- CORE BATCH PROCESSING ---

def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_parser",
        step="start",
        outcome=DNAStatus.SUCCESS,
        latency_ms=0.0
    )

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    # Output file paths defined unconditionally at top level
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parser",
            step="read_input",
            outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail="input_file_missing"
        )
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
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parser",
            step="read_input",
            outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail="empty_input_file"
        )
        return

    full_ledger_data = load_ledger(ledger_path)
    ledger = full_ledger_data.get("ledger", {})
    system_state = full_ledger_data.get("system_state", {"core_heat": 0.0, "last_processed_timestamp": None})

    # --- THERMAL FATIGUE / COOLING DECAY ---
    core_heat = float(system_state.get("core_heat", 0.0))
    last_time_str = system_state.get("last_processed_timestamp")
    now_utc_dt = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    if last_time_str:
        try:
            last_dt = datetime.datetime.strptime(last_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            elapsed_seconds = max(0.0, (now_utc_dt - last_dt).total_seconds())
            cooling_amount = elapsed_seconds * 0.5
            core_heat = max(0.0, core_heat - cooling_amount)
        except Exception:
            pass

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
    initial_ledger_data = json.loads(json.dumps(full_ledger_data))

    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED)
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="deduplicate",
                outcome=DNAStatus.SKIPPED,
                latency_ms=(time.time() - start_time) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail=f"dedupe_hit: {term_outcome}"
            )
            continue

        # Check thermal lockout before parsing new sequence
        if core_heat >= 10.0:
            system_state["core_heat"] = core_heat
            system_state["last_processed_timestamp"] = now_iso
            save_ledger(ledger_path, {"ledger": ledger, "system_state": system_state})

            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parser",
                step="thermal_check",
                outcome=DNAStatus.REFUSED,
                latency_ms=(time.time() - start_time) * 1000,
                idempotency_key=idempotency_key,
                outcome_detail="Thermal Lockout: Heat Accumulation above safety threshold. Wait for dissipation. The system is indifferent to your deadlines."
            )
            raise ThermalOverloadError(
                "Thermal Lockout: Heat Accumulation above threshold. "
                "Wait for dissipation. The system is indifferent to your deadlines."
            )

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS

            # Heat accumulation on success
            core_heat += 2.0

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

        now_utc = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': now_utc
        }
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parser",
            step="parse_sequence",
            outcome=outcome,
            latency_ms=(time.time() - start_time) * 1000,
            idempotency_key=idempotency_key,
            outcome_detail=f"Heat Accumulation: current_core_heat={core_heat}"
        )

    # Persist outputs and ledger if new sequences were processed
    if new_processed_count > 0:
        system_state["core_heat"] = core_heat
        system_state["last_processed_timestamp"] = now_iso
        save_ledger(ledger_path, {"ledger": ledger, "system_state": system_state})

        # ATOMIC WRITE PATTERN FOR OUTPUT FILES
        with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
            tmp_json = os.path.join(tmp_dir, 'output.json')
            tmp_csv = os.path.join(tmp_dir, 'output.csv')

            try:
                # 1) Write JSON output to temp
                with open(tmp_json, 'w', encoding='utf-8') as jf:
                    json.dump(parsed_json, jf, indent=2)
                    jf.flush()
                    os.fsync(jf.fileno())

                # 2) Write CSV output to temp
                fieldnames = sorted(all_flattened_keys)
                with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in csv_rows:
                        out = {k: row.get(k, '') for k in fieldnames}
                        writer.writerow(out)
                    cf.flush()
                    os.fsync(cf.fileno())

                # 3) Atomic rename
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                raise AtomicWriteError("Failed to write output files atomically") from e

    total_latency = (time.time() - start_time) * 1000
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_parser",
        step="end",
        outcome=DNAStatus.SUCCESS,
        latency_ms=total_latency,
        outcome_detail=f"processed_count={new_processed_count}"
    )

# Maintain backward compatibility alias
main = run_batch

if __name__ == '__main__':
    main()
