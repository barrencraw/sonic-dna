import json
import io
import contextlib
from utils.dtos import DNAResult, ProcessingOutcome
from utils.observability import StructuredLogger

def test_dna_result_dto_structure():
    """Verify DNAResult DTO has expected fields."""
    result = DNAResult(dna="V100", rule="Volume", values={"level": 100}, outcome=ProcessingOutcome.SUCCESS)
    assert result.dna == "V100"
    assert result.rule == "Volume"
    assert result.values == {"level": 100}
    assert result.outcome == ProcessingOutcome.SUCCESS

def test_observability_contract_format():
    """Verify StructuredLogger emits correctly formatted JSON with required fields."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        logger = StructuredLogger(chain_name="test_chain", correlation_id="test_corr")
        logger.log(step="test_step", outcome="test_outcome", extra_field="extra")

    log_line = output.getvalue().strip()
    assert log_line.startswith("[OBSERVABILITY] ")

    json_part = log_line[len("[OBSERVABILITY] "):]
    log_data = json.loads(json_part)

    assert log_data["correlation_id"] == "test_corr"
    assert log_data["chain_name"] == "test_chain"
    assert log_data["step"] == "test_step"
    assert log_data["outcome"] == "test_outcome"
    assert "timestamp" in log_data
    assert log_data["extra_field"] == "extra"

def test_processing_outcome_enum():
    """Verify ProcessingOutcome enum values."""
    assert ProcessingOutcome.SUCCESS.value == "success"
    assert ProcessingOutcome.ERROR.value == "error"
    assert ProcessingOutcome.DEDUPE.value == "dedupe"
