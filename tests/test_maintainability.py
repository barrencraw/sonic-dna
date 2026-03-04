import pytest
import os
import json
from utils.dna_calculator import DNACalculator, DNAResult
from utils.dna_ui import run_batch, ProcessingOutcome

def test_dna_result_structure():
    """Ensure DNACalculator.parse returns a DNAResult object."""
    calc = DNACalculator()
    # Find a valid rule and test string
    rule = next(iter(calc.rules.values()))
    dna_str = rule.prefix + "0" * 20 # Dummy DNA string, might fail parse but should return DNAResult

    result = calc.parse(dna_str)
    assert isinstance(result, DNAResult)
    assert hasattr(result, 'dna_string')
    assert hasattr(result, 'rule_name')
    assert hasattr(result, 'values')
    assert hasattr(result, 'error')

def test_observability_log_format(capsys):
    """Ensure logs follow the observability contract."""
    # We need to trigger run_batch which uses the logger
    # Create a dummy input file if not exists
    os.makedirs("data/raw", exist_ok=True)
    input_path = "data/raw/toSequence.txt"
    with open(input_path, "w") as f:
        f.write("VOL100\n") # Assuming VOL is a prefix for Volume

    run_batch(correlation_id="test-correlation-id")

    captured = capsys.readouterr()
    logs = [line for line in captured.out.split('\n') if line.startswith('[OBSERVABILITY]')]

    assert len(logs) > 0
    for log_line in logs:
        log_json = json.loads(log_line.replace('[OBSERVABILITY] ', ''))
        assert "correlation_id" in log_json
        assert "chain_name" in log_json
        assert "step" in log_json
        assert "timestamp" in log_json
        assert "level" in log_json
        assert "service" in log_json

def test_processing_outcome_enum():
    """Ensure ProcessingOutcome enum has required members."""
    assert ProcessingOutcome.SUCCESS.value == "success"
    assert ProcessingOutcome.ERROR.value == "error"
    assert ProcessingOutcome.DEDUPE.value == "dedupe"
