#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from datetime import datetime, timezone
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError

# ─── ENUM & EXCEPTION TAXONOMY ────────────────────────────────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

    @property
    def success(self):
        return self == DNAStatus.SUCCESS

    @property
    def error(self):
        return self == DNAStatus.ERROR

    @property
    def skipped(self):
        return self == DNAStatus.SKIPPED

    @property
    def refused(self):
        return self == DNAStatus.REFUSED


class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass


class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass


class InputReadError(DNAProcessingError):
    """Raised when reading input DNA sequence file fails."""
    pass


class PersistenceError(DNAProcessingError):
    """Base class for persistence errors."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when loading processed ledger fails or is corrupted."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving processed ledger fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when atomic output file write fails."""
    pass


# ─── STRUCTURED LOGGING ───────────────────────────────────────────────────────

def log_structured(correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail=None):
    log_data = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name or "dna_batch_processing",
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG:{json.dumps(log_data)}")
    return log_data


# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

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
    except Exception as e:
        raise InputReadError(f"Failed to read input file: {input_path}") from e
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
                content = json.load(f)
                if isinstance(content, dict):
                    return content
                return {}
        except Exception as e:
            raise LedgerLoadError(f"Corrupted or unreadable ledger file at {ledger_path}") from e
    return {}


def save_ledger(ledger_path, ledger):
    try:
        dir_name = os.path.dirname(ledger_path) or '.'
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
            json.dump(ledger, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_name = tf.name
        os.replace(tmp_name, ledger_path)
    except Exception as e:
        if 'tmp_name' in locals() and os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass
        raise LedgerSaveError(f"Failed to save processed ledger to {ledger_path}") from e


# ─── BATCH PROCESSING ENTRYPOINT ──────────────────────────────────────────────

def run_batch(correlation_id=None, actor_id="batch_parser", project_root=None):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())

    if project_root is None:
        project_root = os.getcwd()

    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        elapsed = (time.time() - start_time) * 1000
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_processing",
            step="batch_start",
            outcome=DNAStatus.ERROR.value,
            latency_ms=elapsed,
            idempotency_key="batch_init",
            outcome_detail=f"Input file not found: {input_file}"
        )
        return {
            "status": DNAStatus.ERROR.value,
            "processed": 0,
            "skipped": 0,
            "errors": 1,
            "detail": "Input file not found"
        }

    # Instantiate calculator
    rules_path = os.path.join(project_root, 'rules')
    try:
        calculator = DNACalculator(rules_folder=rules_path)
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_processing",
            step="rule_loading",
            outcome=DNAStatus.ERROR.value,
            latency_ms=elapsed,
            idempotency_key="batch_init",
            outcome_detail=f"Could not load rules from {rules_path}: {e}"
        )
        raise RuleLoadError(f"Could not load rules from {rules_path}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        elapsed = (time.time() - start_time) * 1000
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_processing",
            step="read_input",
            outcome=DNAStatus.SKIPPED.value,
            latency_ms=elapsed,
            idempotency_key="batch_init",
            outcome_detail="No DNA sequences found in input file"
        )
        return {
            "status": DNAStatus.SKIPPED.value,
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "detail": "Empty input file"
        }

    ledger_data = load_ledger(ledger_path)
    if isinstance(ledger_data, dict) and 'ledger' in ledger_data:
        ledger = ledger_data['ledger']
    else:
        ledger = ledger_data

    # Load existing JSON output
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    parsed_json = []
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, 'r', encoding='utf-8') as jf:
                content = json.load(jf)
                if isinstance(content, list):
                    parsed_json = content
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
                if reader.fieldnames:
                    all_flattened_keys = set(reader.fieldnames)
                    csv_rows = list(reader)
        except Exception:
            pass

    new_processed_count = 0
    skipped_count = 0
    error_count = 0

    for dna_sequence in dna_sequence_list:
        idempotency_key = dna_sequence
        seq_start = time.time()

        if idempotency_key in ledger:
            skipped_count += 1
            existing_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            seq_elapsed = (time.time() - seq_start) * 1000
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_processing",
                step="dedupe_check",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=seq_elapsed,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit, previously processed as: {existing_outcome}"
            )
            continue

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,  # Legacy key backward compatibility
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_sequence
            flat['dna'] = dna_sequence  # Legacy key
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.SUCCESS.value
            new_processed_count += 1

        except RuleParseError as e:
            error_count += 1
            entry = {
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,  # Legacy key
                'error': str(e)
            }
            parsed_json.append(entry)

            flat = {'dna_sequence': dna_sequence, 'dna': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())

            outcome = DNAStatus.ERROR.value
            new_processed_count += 1

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        seq_elapsed = (time.time() - seq_start) * 1000
        log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name="dna_batch_processing",
            step="parse_sequence",
            outcome=outcome,
            latency_ms=seq_elapsed,
            idempotency_key=idempotency_key,
            outcome_detail=f"Sequence parsed with outcome: {outcome}"
        )

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN:
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

        # Save ledger
        save_ledger(ledger_path, ledger_data)

    total_elapsed = (time.time() - start_time) * 1000
    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_processing",
        step="batch_complete",
        outcome=DNAStatus.SUCCESS.value,
        latency_ms=total_elapsed,
        idempotency_key="batch_summary",
        outcome_detail=f"Processed: {new_processed_count}, Skipped: {skipped_count}, Errors: {error_count}"
    )

    return {
        "status": DNAStatus.SUCCESS.value,
        "processed": new_processed_count,
        "skipped": skipped_count,
        "errors": error_count,
        "total": len(dna_sequence_list)
    }


main = run_batch


if __name__ == '__main__':
    main()
