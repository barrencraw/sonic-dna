#!/usr/bin/env python3
import os
import json
import csv
import time
import tempfile
from enum import Enum
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

# --- Exceptions taxonomy ---
class DNAProcessingError(Exception):
    """Base class for DNA processing errors."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading the input file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass

class PersistenceError(DNAProcessingError):
    """Base class for persistence and writing errors."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading the ledger fails (e.g. file is corrupted)."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when writing output files atomically fails."""
    pass


class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"


class BatchResult:
    def __init__(self, status: str, processed_count: int, total_ledger_items: int):
        self.status = status  # 'SUCCESS' or 'NO_NEW_ITEMS'
        self.processed_count = processed_count
        self.total_ledger_items = total_ledger_items

    def __repr__(self):
        return f"BatchResult(status={self.status!r}, processed_count={self.processed_count}, total_ledger_items={self.total_ledger_items})"


def log_structured(correlation_id=None, actor_id=None, chain_name=None, step=None, outcome=None, latency_ms=0, idempotency_key=None, outcome_detail=None):
    timestamp_iso = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    log_dict = {
        "timestamp": timestamp_iso,
        "correlation_id": correlation_id or "system",
        "actor_id": actor_id or "system",
        "chain_name": chain_name or "dna_batch_chain",
        "step": step or "unknown",
        "outcome": outcome or "unknown",
        "latency_ms": int(latency_ms) if latency_ms is not None else 0,
        "idempotency_key": idempotency_key or "",
        "outcome_detail": outcome_detail or ""
    }
    print(f"JSON_LOG: {json.dumps(log_dict)}")


def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def read_input_file(input_path):
    """
    Reads `toSequence.txt` under data/raw; each line is one DNA sequence.
    Returns a list of DNA sequences (stripped, non-empty).
    """
    try:
        dna_sequence_list = []
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequence_list.append(s)
        return dna_sequence_list
    except Exception as e:
        raise InputReadError(f"Failed to read input file {input_path}") from e


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
            raise LedgerLoadError(f"Ledger file is corrupted or unreadable: {ledger_path}") from e
    return {}


def save_ledger(ledger_path, ledger):
    ledger_dir = os.path.dirname(ledger_path) or '.'
    ensure_folder(ledger_dir)
    temp_fd = None
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(dir=ledger_dir, prefix='.ledger_tmp_')
        temp_fd = os.fdopen(fd, 'w', encoding='utf-8')
        json.dump(ledger, temp_fd, indent=2)
        temp_fd.flush()
        os.fsync(fd)
        temp_fd.close()
        temp_fd = None
        os.replace(temp_path, ledger_path)
    except Exception as e:
        if temp_fd is not None:
            try:
                temp_fd.close()
            except Exception:
                pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise LedgerSaveError(f"Failed to save ledger atomically to {ledger_path}") from e


def run_batch(correlation_id=None, actor_id=None):
    start_time = time.time()
    error_occurred = False
    new_processed_count = 0
    ledger = {}

    # Pre-define output file paths to prevent UnboundLocalError
    project_root = os.getcwd()
    output_folder = os.path.join(project_root, 'data', 'output')
    json_output_path = os.path.join(output_folder, 'toSequence_parsed.json')
    csv_output_path = os.path.join(output_folder, 'toSequence_parsed.csv')

    log_structured(
        correlation_id=correlation_id,
        actor_id=actor_id,
        chain_name="dna_batch_chain",
        step="start_batch",
        outcome="processing"
    )

    try:
        raw_folder = os.path.join(project_root, 'data', 'raw')
        ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
        ensure_folder(output_folder)

        input_file = os.path.join(raw_folder, 'toSequence.txt')
        if not os.path.isfile(input_file):
            # If no file exists, return NO_NEW_ITEMS with 0 items
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_chain",
                step="end_batch",
                outcome="NO_NEW_ITEMS",
                latency_ms=int((time.time() - start_time) * 1000),
                outcome_detail=f"Input file not found: {input_file}"
            )
            return BatchResult(status='NO_NEW_ITEMS', processed_count=0, total_ledger_items=0)

        # Instantiate calculator
        try:
            calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
        except Exception as e:
            raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

        # Read DNA strings (canonical name: dna_sequence_list)
        dna_sequence_list = read_input_file(input_file)

        if not dna_sequence_list:
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_chain",
                step="end_batch",
                outcome="NO_NEW_ITEMS",
                latency_ms=int((time.time() - start_time) * 1000),
                outcome_detail="No DNA sequences found in toSequence.txt"
            )
            return BatchResult(status='NO_NEW_ITEMS', processed_count=0, total_ledger_items=0)

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

        for dna_sequence in dna_sequence_list:
            idempotency_key = dna_sequence
            if idempotency_key in ledger:
                cached_outcome = ledger[idempotency_key].get('terminal_outcome', 'success')
                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name="dna_batch_chain",
                    step="deduplication_hit",
                    outcome="skipped",
                    idempotency_key=idempotency_key,
                    outcome_detail=cached_outcome
                )
                continue

            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_chain",
                step="process_sequence",
                outcome="processing",
                idempotency_key=idempotency_key
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

                # Flatten for CSV
                flat = flatten_parsed(result['rule'], result['values'])
                flat['dna'] = dna_sequence
                flat['dna_sequence'] = dna_sequence
                flat['rule'] = result['rule']
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.SUCCESS

            except RuleParseError as e:
                # On parse error, record as error entry
                parsed_json.append({
                    'dna': dna_sequence,
                    'dna_sequence': dna_sequence,
                    'error': str(e)
                })
                # Also put a row in CSV listing error
                flat = {
                    'dna': dna_sequence,
                    'dna_sequence': dna_sequence,
                    'error': str(e)
                }
                csv_rows.append(flat)
                all_flattened_keys.update(flat.keys())
                outcome = DNAStatus.ERROR

            # Update ledger in memory
            ledger[idempotency_key] = {
                'terminal_outcome': outcome.value,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            new_processed_count += 1

            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_chain",
                step="process_sequence_complete",
                outcome=outcome.value,
                idempotency_key=idempotency_key,
                outcome_detail="Parsed successfully" if outcome == DNAStatus.SUCCESS else "RuleParseError"
            )

        # Write output files & ledger if there are new processed items
        if new_processed_count > 0:
            # 1. Save ledger atomically first
            save_ledger(ledger_path, ledger)

            # 2. Save JSON & CSV atomically
            with tempfile.TemporaryDirectory(dir=output_folder) as tmp_dir:
                tmp_json = os.path.join(tmp_dir, 'output.json')
                tmp_csv = os.path.join(tmp_dir, 'output.csv')

                try:
                    # Write JSON output to temp
                    with open(tmp_json, 'w', encoding='utf-8') as jf:
                        json.dump(parsed_json, jf, indent=2)
                        jf.flush()
                        os.fsync(jf.fileno())

                    # Write CSV output to temp
                    fieldnames = sorted(all_flattened_keys)
                    with open(tmp_csv, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        for row in csv_rows:
                            out = {k: row.get(k, '') for k in fieldnames}
                            writer.writerow(out)
                        cf.flush()
                        os.fsync(cf.fileno())

                    # Atomic rename (commit)
                    os.replace(tmp_json, json_output_path)
                    os.replace(tmp_csv, csv_output_path)

                except Exception as e:
                    raise AtomicWriteError("Failed to write output files atomically") from e

            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_chain",
                step="commit_batch",
                outcome="success",
                outcome_detail=f"Processed {new_processed_count} items."
            )

        status_str = 'SUCCESS' if new_processed_count > 0 else 'NO_NEW_ITEMS'
        return BatchResult(status=status_str, processed_count=new_processed_count, total_ledger_items=len(ledger))

    except Exception as e:
        error_occurred = True
        raise e

    finally:
        latency_ms = int((time.time() - start_time) * 1000)

        # Finally block cleanup error log handler
        try:
            # Code to simulate finally-block cleanup (none strictly required here, but we implement the logic)
            pass
        except Exception as cleanup_err:
            try:
                log_structured(
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    chain_name="dna_batch_chain",
                    step="cleanup_failure",
                    outcome="error",
                    outcome_detail=str(cleanup_err)
                )
            except Exception:
                pass
            if not error_occurred:
                raise PersistenceError(f"Cleanup failure: {cleanup_err}") from cleanup_err

        # Standard final batch log
        final_outcome = "error" if error_occurred else ("SUCCESS" if new_processed_count > 0 else "NO_NEW_ITEMS")
        try:
            log_structured(
                correlation_id=correlation_id,
                actor_id=actor_id,
                chain_name="dna_batch_chain",
                step="end_batch",
                outcome=final_outcome,
                latency_ms=latency_ms,
                outcome_detail=f"Batch finished. Processed: {new_processed_count}"
            )
        except Exception:
            pass

# Maintain backwards compatibility for main.py & tests
main = run_batch
