#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

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

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key=None, outcome_detail=None):
    log_data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'correlation_id': correlation_id,
        'actor_id': actor_id,
        'chain_name': chain_name,
        'step': step,
        'outcome': outcome,
        'latency_ms': latency_ms,
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_data)}")

def run_batch(correlation_id=None, actor_id='batch_parser'):
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    chain_name = 'dna_batch_parsing'
    start_time = time.time()

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step='start',
        outcome='success',
        latency_ms=0,
        outcome_detail='Batch processing initiated'
    )

    # Determine file paths
    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        print(f"[ERROR] Input file not found: {input_file}")
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step='end',
            outcome='error',
            latency_ms=int((time.time() - start_time) * 1000),
            outcome_detail='Input file not found'
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step='end',
            outcome='error',
            latency_ms=int((time.time() - start_time) * 1000),
            outcome_detail=f"RuleLoadError: {str(e)}"
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA strings
    try:
        dna_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step='end',
            outcome='error',
            latency_ms=int((time.time() - start_time) * 1000),
            outcome_detail=f"DNAProcessingError: {str(e)}"
        )
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_list:
        print("[WARN] No DNA strings found in toSequence.txt")
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step='end',
            outcome='success',
            latency_ms=int((time.time() - start_time) * 1000),
            outcome_detail='No DNA strings found in input file'
        )
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
    for dna_str in dna_list:
        seq_start = time.time()
        idempotency_key = dna_str
        if idempotency_key in ledger:
            term_outcome = ledger[idempotency_key].get('terminal_outcome', 'unknown')
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={term_outcome}")
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name=chain_name,
                step='dedupe_check',
                outcome='skipped',
                latency_ms=int((time.time() - seq_start) * 1000),
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit, previously processed as {term_outcome}"
            )
            continue

        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome=processing")

        try:
            result = calculator.parse(dna_str)
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
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_str,
                'error': str(e)
            })
            # Also put a row in CSV listing error
            flat = {'dna': dna_str, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        new_processed_count += 1

        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step='parse_sequence',
            outcome='success' if outcome == 'success' else 'error',
            latency_ms=int((time.time() - seq_start) * 1000),
            idempotency_key=idempotency_key,
            outcome_detail=outcome
        )

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
        # 1. Write JSON and CSV to temp directory under output_folder
        # 2. Flush & fsync
        # 3. Rename (replace) atomically
        json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
        csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

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

                # 3) Atomic rename (commit)
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name=chain_name,
                    step='atomic_write',
                    outcome='error',
                    latency_ms=int((time.time() - start_time) * 1000),
                    outcome_detail=f"PersistenceError: {str(e)}"
                )
                raise PersistenceError("Failed to write output files atomically") from e

        # Save ledger only after output files are atomically written
        save_ledger(ledger_path, ledger)

    total_latency = int((time.time() - start_time) * 1000)
    print(f"[OK] Processed {new_processed_count} new DNA strings. Total in ledger: {len(ledger)}")
    print(f"     JSON → {json_output_path}")
    print(f"     CSV  → {csv_output_path}")

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name=chain_name,
        step='end',
        outcome='success',
        latency_ms=total_latency,
        outcome_detail=f"Processed {new_processed_count} new sequences. Total ledger: {len(ledger)}"
    )

main = run_batch

if __name__ == '__main__':
    main()
