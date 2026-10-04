#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
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

class LedgerLoadError(PersistenceError):
    """Raised when reading or parsing ledger file fails."""
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
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s:
                dna_sequence_list.append(s)
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
        raise PersistenceError(f"Failed to save ledger to {ledger_path}") from e

def log_structured(chain_name, step, outcome, latency_ms=0, correlation_id=None, actor_id="batch_parser", idempotency_key=None, outcome_detail=None):
    log_data = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id,
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key or "N/A"
    }
    if outcome_detail:
        log_data["outcome_detail"] = outcome_detail
    print(f"JSON_LOG: {json.dumps(log_data)}")

def main(correlation_id=None):
    start_time = time.time()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    log_structured(
        chain_name="dna_batch_processing",
        step="start",
        outcome="success",
        correlation_id=correlation_id,
        actor_id="batch_parser"
    )

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            chain_name="dna_batch_processing",
            step="load_input",
            outcome="failure",
            correlation_id=correlation_id,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            chain_name="dna_batch_processing",
            step="load_rules",
            outcome="error",
            correlation_id=correlation_id,
            outcome_detail=str(e)
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        log_structured(
            chain_name="dna_batch_processing",
            step="read_input",
            outcome="error",
            correlation_id=correlation_id,
            outcome_detail=str(e)
        )
        raise DNAProcessingError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        log_structured(
            chain_name="dna_batch_processing",
            step="parse_sequences",
            outcome="skipped",
            correlation_id=correlation_id,
            outcome_detail="No DNA sequences found in toSequence.txt"
        )
        return

    ledger = load_ledger(ledger_path)

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
    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        seq_start_time = time.time()

        if idempotency_key in ledger:
            log_structured(
                chain_name="dna_batch_processing",
                step="deduplication",
                outcome="skipped",
                latency_ms=(time.time() - seq_start_time) * 1000,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit, terminal_outcome={ledger[idempotency_key]['terminal_outcome']}"
            )
            print(f"[Idempotency] key={idempotency_key} dedupe_hit=True terminal_outcome={ledger[idempotency_key]['terminal_outcome']}")
            continue

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
            outcome = "success"

        except RuleParseError as e:
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = f"error: {str(e)}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        seq_latency = (time.time() - seq_start_time) * 1000
        log_structured(
            chain_name="dna_batch_processing",
            step="parse_sequence",
            outcome="success" if outcome == "success" else "error",
            latency_ms=seq_latency,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            outcome_detail=outcome
        )
        print(f"[Idempotency] key={idempotency_key} dedupe_hit=False terminal_outcome={outcome}")
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

            except Exception as e:
                log_structured(
                    chain_name="dna_batch_processing",
                    step="atomic_persistence",
                    outcome="error",
                    correlation_id=correlation_id,
                    outcome_detail=str(e)
                )
                raise PersistenceError("Failed to write output files atomically") from e

    total_latency = (time.time() - start_time) * 1000
    log_structured(
        chain_name="dna_batch_processing",
        step="complete",
        outcome="success",
        latency_ms=total_latency,
        correlation_id=correlation_id,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

if __name__ == '__main__':
    main()
