import json
import io
from contextlib import redirect_stdout
from utils.dtos import DNAResult, ProcessingOutcome
from utils.observability import StructuredLogger

def test_dna_result_structure():
    """Verify DNAResult dataclass has the expected fields."""
    res = DNAResult(dna_string="TEST")
    assert hasattr(res, "dna_string")
    assert hasattr(res, "rule_name")
    assert hasattr(res, "values")
    assert hasattr(res, "outcome")
    assert hasattr(res, "error_message")
    assert res.outcome == ProcessingOutcome.SUCCESS

def test_observability_contract():
    """Verify StructuredLogger emits valid JSON with [OBSERVABILITY] prefix."""
    logger = StructuredLogger(chain_name="test_chain")
    f = io.StringIO()
    with redirect_stdout(f):
        logger.log(step="test_step", outcome="success", correlation_id="test_cid")

    output = f.getvalue().strip()
    assert output.startswith("[OBSERVABILITY] ")

    json_part = output[len("[OBSERVABILITY] "):]
    log_data = json.loads(json_part)

    expected_keys = {"chain_name", "version", "step", "outcome", "correlation_id", "timestamp"}
    for key in expected_keys:
        assert key in log_data

    assert log_data["chain_name"] == "test_chain"
    assert log_data["step"] == "test_step"
    assert log_data["correlation_id"] == "test_cid"
