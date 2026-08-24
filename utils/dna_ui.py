#!/usr/bin/env python3
import os
import json
import csv
import time
import datetime
import uuid
import tempfile
from enum import Enum
from utils.dna_calculator import DNACalculator, RuleParseError


# ─── DOMAIN & EXCEPTION TAXONOMY ──────────────────────────────────────────────

class DNAStatus(str, Enum):
    """Explicit terminal states for DNA processing lifecycle."""
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    REFUSED = "refused"

    def __str__(self):
        return self.value


class DNAProcessingError(Exception):
    """Base exception for all DNA processing errors."""
    pass


class InputReadError(DNAProcessingError):
    """Raised when reading input DNA sequences fails."""
    pass


class RuleLoadError(DNAProcessingError):
    """Raised when rules cannot be loaded."""
    pass


class PersistenceError(DNAProcessingError):
    """Base class for storage and persistence failures."""
    pass


class LedgerLoadError(PersistenceError):
    """Raised when reading the processed ledger fails due to corruption."""
    pass


class LedgerSaveError(PersistenceError):
    """Raised when saving the processed ledger fails."""
    pass


class AtomicWriteError(PersistenceError):
    """Raised when writing or replacing output files fails atomically."""
    pass


# ─── STRUCTURED LOGGING HYGIENE ────────────────────────────────────────────────

def log_structured(
    correlation_id,
    actor_id,
    chain_name,
    step,
    outcome,
    latency_ms=0.0,
    idempotency_key=None,
    outcome_detail=""
):
    """
    Emits structured telemetry JSON logs prefixed with 'JSON_LOG:'.
    Standardized fields:
      - timestamp (UTC ISO 8601)
      - correlation_id
      - actor_id
      - chain_name
      - step
      - outcome
      - latency_ms
      - idempotency_key
      - outcome_detail
    """
    log_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "actor_id": actor_id or "batch_parser",
        "chain_name": chain_name or "dna_batch_parser",
        "step": step,
        "outcome": str(outcome),
        "latency_ms": round(latency_ms, 2),
        "idempotency_key": idempotency_key,
        "outcome_detail": outcome_detail
    }
    print(f"JSON_LOG: {json.dumps(log_entry)}")
    return log_entry


# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def ensure_folder(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def read_input_file(input_path):
    """
    Reads toSequence.txt under data/raw; each line is one DNA sequence.
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
            raise LedgerLoadError(f"Failed to load corrupted ledger file '{ledger_path}': {e}") from e
    return {}


def save_ledger(ledger_path, ledger):
    try:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2)
    except Exception as e:
        raise LedgerSaveError(f"Failed to save ledger file '{ledger_path}': {e}") from e


# ─── BATCH PARSER ENTRYPOINT ───────────────────────────────────────────────────

def run_batch(correlation_id=None, actor_id="batch_parser"):
    start_time = time.time()
    correlation_id = correlation_id or str(uuid.uuid4())
    chain_name = "dna_batch_parser"

    project_root = os.getcwd()
    raw_folder = os.path.join(project_root, 'data', 'raw')
    output_folder = os.path.join(project_root, 'data', 'output')
    ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
    ensure_folder(output_folder)

    input_file = os.path.join(raw_folder, 'toSequence.txt')
    if not os.path.isfile(input_file):
        log_structured(
            correlation_id, actor_id, chain_name,
            step="input_read", outcome=DNAStatus.REFUSED,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=f"Input file not found: {input_file}"
        )
        return

    # Instantiate calculator
    try:
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
    except Exception as e:
        log_structured(
            correlation_id, actor_id, chain_name,
            step="rule_load", outcome=DNAStatus.ERROR,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail=str(e)
        )
        raise RuleLoadError(f"Could not load rules from {os.path.join(project_root, 'rules')}") from e

    # Read DNA sequences
    dna_sequence_list = read_input_file(input_file)

    if not dna_sequence_list:
        log_structured(
            correlation_id, actor_id, chain_name,
            step="input_read", outcome=DNAStatus.SKIPPED,
            latency_ms=(time.time() - start_time) * 1000,
            outcome_detail="No DNA sequences found in input file"
        )
        return

    ledger = load_ledger(ledger_path)
    # Support both structured ledger dictionary {'ledger': {...}} and flat ledger
    ledger_data = ledger.get('ledger', ledger)

    # 1) Load existing JSON output
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
        idempotency_key = dna_sequence
        if idempotency_key in ledger_data:
            existing_outcome = ledger_data[idempotency_key].get('terminal_outcome', DNAStatus.SUCCESS.value)
            log_structured(
                correlation_id, actor_id, chain_name,
                step="dedupe_check", outcome=DNAStatus.SKIPPED,
                idempotency_key=idempotency_key,
                outcome_detail=f"Dedupe hit; previously logged with outcome '{existing_outcome}'"
            )
            continue

        try:
            result = calculator.parse(dna_sequence)
            entry = {
                'dna_sequence': dna_sequence,
                'dna': dna_sequence, # Legacy key maintained for backwards compatibility
                'rule': result['rule'],
                'parsed': result['values']
            }
            parsed_json.append(entry)

            # Flatten for CSV
            flat = flatten_parsed(result['rule'], result['values'])
            flat['dna_sequence'] = dna_sequence
            flat['dna'] = dna_sequence
            flat['rule'] = result['rule']
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.SUCCESS

            log_structured(
                correlation_id, actor_id, chain_name,
                step="parse_sequence", outcome=DNAStatus.SUCCESS,
                idempotency_key=idempotency_key,
                outcome_detail=f"Successfully parsed rule '{result['rule']}'"
            )

        except RuleParseError as e:
            parsed_json.append({
                'dna_sequence': dna_sequence,
                'dna': dna_sequence,
                'error': str(e)
            })
            flat = {'dna_sequence': dna_sequence, 'dna': dna_sequence, 'error': str(e)}
            csv_rows.append(flat)
            all_flattened_keys.update(flat.keys())
            outcome = DNAStatus.ERROR

            log_structured(
                correlation_id, actor_id, chain_name,
                step="parse_sequence", outcome=DNAStatus.ERROR,
                idempotency_key=idempotency_key,
                outcome_detail=str(e)
            )

        ledger_data[idempotency_key] = {
            'terminal_outcome': str(outcome),
            'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        new_processed_count += 1

    if new_processed_count > 0:
        # ATOMIC WRITE PATTERN
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

        # Save ledger only after atomic write succeeds
        save_ledger(ledger_path, ledger)

    latency_ms = (time.time() - start_time) * 1000
    log_structured(
        correlation_id, actor_id, chain_name,
        step="batch_complete", outcome=DNAStatus.SUCCESS,
        latency_ms=latency_ms,
        outcome_detail=f"Processed {new_processed_count} new DNA sequences. Total in ledger: {len(ledger_data)}"
    )

# Alias for backward compatibility
main = run_batch


if __name__ == '__main__':
    run_batch()
