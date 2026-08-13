#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

# Exception taxonomy for DNA batch processing
class DNAProcessingError(Exception):
    """Base class for all DNA processing errors."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence-related errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading a corrupted ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic write operations fail."""
    pass


# Explicit terminal states
class DNAStatus:
    SUCCESS = 'success'
    ERROR = 'error'
    SKIPPED = 'skipped'
    REFUSED = 'refused'


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
    """Loads the processed ledger. Raises LedgerLoadError if corrupted."""
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            raise LedgerLoadError(f"Failed to load corrupted ledger: {ledger_path}") from e
    return {}


def save_ledger(ledger_path, ledger):
    """Saves the processed ledger. Raises LedgerSaveError if fails."""
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger: {ledger_path}") from e


def log_structured(correlation_id, chain_name, step, outcome, latency_ms, actor_id, idempotency_key, outcome_detail=None):
    """Emits a structured JSON log prefixed with JSON_LOG:."""
    log_data = {
        'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'correlation_id': correlation_id or "N/A",
        'actor_id': actor_id or "N/A",
        'chain_name': chain_name or "dna_batch_processing",
        'step': step,
        'outcome': outcome,
        'latency_ms': int(latency_ms),
        'idempotency_key': idempotency_key,
        'outcome_detail': outcome_detail or ""
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")


def run_batch(correlation_id=None):
    """
    Processes DNA sequences from toSequence.txt in batch.
    Uses structured logs, explicit error states, and atomic writing.
    """
    start_time = time.time()
    actor_id = "system_watcher"

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            chain_name="dna_batch_processing",
            step="initial_check",
            outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            idempotency_key="N/A",
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    try:
        dna_sequence_list = read_input_file(input_file)
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_file}") from e

    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            chain_name="dna_batch_processing",
            step="initial_check",
            outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            idempotency_key="N/A",
            outcome_detail="No DNA sequences found in toSequence.txt"
        )
        return

    # Load existing ledger
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

    for dna_sequence in dna_sequence_list:
        step_start_time = time.time()
        idempotency_key = dna_sequence

        # Idempotency check: Skip if sequence exists in ledger with terminal outcome
        if idempotency_key in ledger:
            # Maintain backward compatibility: ledger could be structured or flat.
            # If flat ledger: ledger[idempotency_key] is a dict with 'terminal_outcome'
            # Let's handle both flat ledger and structured ledger
            entry = ledger[idempotency_key]
            existing_outcome = None
            if isinstance(entry, dict):
                existing_outcome = entry.get('terminal_outcome')

            if existing_outcome in [DNAStatus.SUCCESS, DNAStatus.ERROR]:
                log_structured(
                    correlation_id=correlation_id,
                    chain_name="dna_batch_processing",
                    step="idempotency_check",
                    outcome=DNAStatus.SKIPPED,
                    latency_ms=(time.time() - step_start_time) * 1000,
                    actor_id=actor_id,
                    idempotency_key=idempotency_key,
                    outcome_detail=f"Dedupe hit. Already processed with outcome {existing_outcome}."
                )
                continue

        # Processing new sequence
        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,  # Maintain compatibility with both legacy and modern keys
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna'] = dna_sequence
            flat['dna_sequence'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.SUCCESS
            outcome_detail = "Successfully parsed DNA sequence"

        except RuleParseError as e:
            # On parse error, record as error entry
            parsed_json.append({
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            })
            flat = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            }
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.ERROR
            outcome_detail = f"Parse error: {str(e)}"

        # Save outcome to ledger state (in-memory)
        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        # Emit structured log for sequence parsing decision point
        log_structured(
            correlation_id=correlation_id,
            chain_name="dna_batch_processing",
            step="parse_sequence",
            outcome=outcome,
            latency_ms=(time.time() - step_start_time) * 1000,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )
        new_processed_count += 1

    # Persist data only if new DNA sequences were processed
    if new_processed_count > 0:
        # Save ledger first
        save_ledger(ledger_path, ledger)

        # Write output JSON & CSV atomically
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
                raise AtomicWriteError("Failed to write output files atomically") from e

    # Structured log for overall batch outcome
    log_structured(
        correlation_id=correlation_id,
        chain_name="dna_batch_processing",
        step="batch_completed",
        outcome=DNAStatus.SUCCESS if new_processed_count > 0 else DNAStatus.SKIPPED,
        latency_ms=(time.time() - start_time) * 1000,
        actor_id=actor_id,
        idempotency_key="N/A",
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
    )

# Alias maintained for backward compatibility
main = run_batch

if __name__ == '__main__':
    run_batch()
