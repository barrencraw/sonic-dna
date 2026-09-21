#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
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

class InputReadError(DNAProcessingError):
    """Raised when reading input file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when ledger loading fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file write fails."""
    pass

def log_structured(correlation_id=None, actor_id="batch_parser", chain_name="dna_batch_parsing", step="start", outcome="success", latency_ms=0, idempotency_key="", outcome_detail=""):
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": latency_ms,
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

def load_ledger(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}") from e
    return {}

def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}") from e

def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_parsing",
        step="start",
        outcome="success",
        latency_ms=0,
        idempotency_key="",
        outcome_detail="Batch parsing initiated"
    )

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
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parsing",
            step="complete",
            outcome="skipped",
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key="",
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        err = RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}")
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parsing",
            step="error",
            outcome="error",
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key="",
            outcome_detail=str(err)
        )
        raise err from e

    # Read DNA sequences
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        err = InputReadError(f"Failed to read input file: {input_file}")
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parsing",
            step="error",
            outcome="error",
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key="",
            outcome_detail=str(err)
        )
        raise err from e

    if not dna_list:
        print("[WARN] No DNA sequences found in toSequence.txt")
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parsing",
            step="complete",
            outcome="skipped",
            latency_ms=int((time.time() - start_time) * 1000),
            idempotency_key="",
            outcome_detail="No DNA sequences in input file"
        )
        return

    ledger = load_ledger(ledger_path)

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
    existing_ledger = ledger.get('ledger', ledger) if isinstance(ledger, dict) else ledger
    for dna_str in dna_list:
        idempotency_key = dna_str
        if idempotency_key in existing_ledger:
            terminal_outcome = existing_ledger[idempotency_key].get('terminal_outcome', 'processed') if isinstance(existing_ledger[idempotency_key], dict) else 'processed'
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={terminal_outcome}")
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_parsing",
                step="dedupe_check",
                outcome="skipped",
                latency_ms=0,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated sequence. Previous outcome: {terminal_outcome}"
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_str)
            entry = {
                'dna': dna_str,
                'dna_sequence': dna_str,
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_str
            flat['dna_sequence'] = dna_str
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = "success"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_str,
                'dna_sequence': dna_str,
                'error': str(e)
            })
            flat = {'dna': dna_str, 'dna_sequence': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        existing_ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_parsing",
            step="parse_sequence",
            outcome="success" if outcome == "success" else "error",
            latency_ms=0,
            idempotency_key=idempotency_key,
            outcome_detail=outcome
        )
        new_processed_count += 1

    if new_processed_count > 0:
        save_ledger(ledger_path, ledger)

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

                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name="dna_batch_parsing",
                    step="atomic_commit",
                    outcome="success",
                    latency_ms=0,
                    idempotency_key="",
                    outcome_detail=f"Committed {new_processed_count} records to output"
                )

            except Exception as e:
                err = AtomicWriteError("Failed to write output files atomically")
                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name="dna_batch_parsing",
                    step="error",
                    outcome="error",
                    latency_ms=int((time.time() - start_time) * 1000),
                    idempotency_key="",
                    outcome_detail=str(err)
                )
                raise err from e

    latency_ms = int((time.time() - start_time) * 1000)
    print(f"[OK] Processed {new_processed_count} new DNA sequences. Total in ledger: {len(existing_ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_parsing",
        step="complete",
        outcome="success",
        latency_ms=latency_ms,
        idempotency_key="",
        outcome_detail=f"Batch complete. Processed {new_processed_count} new sequences."
    )

main = run_batch

if __name__ == '__main__':
    main()
