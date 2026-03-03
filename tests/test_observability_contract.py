import json
import io
import contextlib
import pytest
from utils.observability import StructuredLogger

def test_structured_logger_format():
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        logger = StructuredLogger(chain_name="test_chain", correlation_id="test_cid")
        logger.log(step="test_step", outcome="test_outcome", extra_field="extra_value")

    log_line = output.getvalue().strip()
    assert log_line.startswith("[OBSERVABILITY] ")

    json_str = log_line[len("[OBSERVABILITY] "):]
    log_data = json.loads(json_str)

    assert log_data["chain_name"] == "test_chain"
    assert log_data["correlation_id"] == "test_cid"
    assert log_data["step"] == "test_step"
    assert log_data["outcome"] == "test_outcome"
    assert log_data["extra_field"] == "extra_value"
    assert "version" in log_data

def test_structured_logger_latency():
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        logger = StructuredLogger(chain_name="test_chain", correlation_id="test_cid")
        logger.log(step="test_step", outcome="success", latency_ms=123.45)

    log_line = output.getvalue().strip()
    json_str = log_line[len("[OBSERVABILITY] "):]
    log_data = json.loads(json_str)

    assert log_data["latency_ms"] == 123.45
