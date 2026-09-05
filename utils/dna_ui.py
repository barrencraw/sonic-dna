#!/usr/bin/env python3
import os
import json
import csv
import time
import uuid
import tempfile
import shutil
from enum import Enum
from datetime import datetime, timezone
from utils.dna_calculator import DNACalculator, RuleParseError

# ─── EXCEPTION TAXONOMY ────────────────────────────────────────────────────────

class DNAProcessingError(Exception):
    """Base exception for DNA processing operations."""
    pass

class InputReadError(DNAProcessingError):
    """Raised when reading input DNA sequence file fails."""
    pass

class RuleLoadError(DNAProcessingError):
    """Raised when loading rule definitions fails."""
    pass

class PersistenceError(DNAProcessingError):
    """Base exception for persistence and output writing operations."""
    pass

class LedgerLoadError(PersistenceError):
    """Raised when loading or parsing the processing ledger fails."""
    pass

class LedgerSaveError(PersistenceError):
    """Raised when saving the processing ledger fails."""
    pass

class AtomicWriteError(PersistenceError):
    """Raised when atomic file replacement or writing fails."""
    pass

# ─── EXPLICIT TERMINAL STATES ─────────────────────────────────────────────────

class DNAStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

# ─── OBSERVABILITY HYGIENE ────────────────────────────────────────────────────

def log_structured(
    correlation_id: str,
    chain_name: str,
    step: str,
    outcome: str,
    latency_ms: float,
    actor_id: str,
    idempotency_key: str = "",
    outcome_detail: str = ""
):
    """Emits standardized structured telemetry logs."""
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log_entry = {
        "timestamp": timestamp,
        "correlation_id": correlation_id or "N/A",
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name,
        "step": step,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG:{json.dumps(log_entry)}")

# ─── UTILITY & HELPER FUNCTIONS ───────────────────────────────────────────────

def ensure_folder(path: str):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def read_input_file(input_path: str) -> list[str]:
    """
    Reads `toSequence.txt` under data/raw; each non-empty line is one DNA sequence.
    Returns a list of stripped DNA sequences.
    """
    dna_sequence_list = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s:
                    dna_sequence_list.append(s)
    except Exception as e:
        raise InputReadError(f"Failed to read input file {input_path}: {e}") from e
    return dna_sequence_list

def flatten_parsed(rule_name: str, values_dict: dict, parent_key: str = '') -> dict:
    """
    Flatten nested dictionary into key-value pairs suitable for CSV export.
    """
    items = {}
    for k, v in values_dict.items():
        new_key = f"{parent_key}.{k}" if parent_key else f"{rule_name}.{k}"
        if isinstance(v, dict):
            items.update(flatten_parsed(rule_name, v, new_key))
        else:
            items[new_key] = v
    return items

def load_ledger(ledger_path: str) -> dict:
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except Exception as e:
            raise LedgerLoadError(f"Failed to load ledger from {ledger_path}: {e}") from e
    return {}

def save_ledger(ledger_path: str, ledger: dict):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger to {ledger_path}: {e}") from e

# ─── CORE BATCH PROCESSOR ──────────────────────────────────────────────────────

def run_batch(correlation_id: str = None, actor_id: str = "batch_parser"):
    start_time = time.time()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    chain_name = "dna_batch_parsing"

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.REFUSED.value,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Load Calculator / Rules
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)
    if not dna_sequence_list:
        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="read_input",
            outcome=DNAStatus.SKIPPED.value,
            latency_ms=(time.time() - start_time) * 1000,
            actor_id=actor_id,
            outcome_detail="No DNA sequences found in input file"
        )
        return

    ledger = load_ledger(ledger_path)

    # Load existing JSON output if present
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

    # Load existing CSV rows if present
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
        seq_start = time.time()
        idempotency_key = dna_sequence

        # Deduplication check
        if idempotency_key in ledger:
            prev_outcome = ledger[idempotency_key].get('terminal_outcome', DNAStatus.SKIPPED.value)
            log_structured(
                correlation_id=correlation_id,
                chain_name=chain_name,
                step="dedupe_check",
                outcome=DNAStatus.SKIPPED.value,
                latency_ms=(time.time() - seq_start) * 1000,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                outcome_detail=f"Deduplicated sequence. Previous outcome: {prev_outcome}"
            )
            continue

        # Parse Sequence
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
            outcome = DNAStatus.SUCCESS.value
            outcome_detail = f"Successfully parsed rule {result['rule']}"

        except RuleParseError as e:
            entry = {
                'dna': dna_sequence,
                'dna_sequence': dna_sequence,
                'error': str(e)
            }
            parsed_json.append(entry)

            flat = {'dna': dna_sequence, 'dna_sequence': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR.value
            outcome_detail = f"Parse error: {str(e)}"

        ledger[idempotency_key] = {
            'terminal_outcome': outcome,
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }

        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="parse_sequence",
            outcome=outcome,
            latency_ms=(time.time() - seq_start) * 1000,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )
        new_processed_count += 1

    # Atomic Write of JSON, CSV, and Ledger if new sequences were processed
    if new_processed_count > 0:
        commit_start = time.time()
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

                # Atomic rename
                os.replace(tmp_json, json_output_path)
                os.replace(tmp_csv, csv_output_path)

            except Exception as e:
                raise AtomicWriteError("Failed to write output files atomically") from e

        # Save ledger
        save_ledger(ledger_path, ledger)

        log_structured(
            correlation_id=correlation_id,
            chain_name=chain_name,
            step="commit_output",
            outcome=DNAStatus.SUCCESS.value,
            latency_ms=(time.time() - commit_start) * 1000,
            actor_id=actor_id,
            outcome_detail=f"Committed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger)}"
        )

# Backward-compatible main function alias
main = run_batch

if __name__ == '__main__':
    run_batch()
