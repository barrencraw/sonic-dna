import inspect
import json
import io
import contextlib
from utils.dna_ui import run_batch, DNAStatus, DNAProcessResult, log_structured

def test_canonical_naming_and_signatures():
    # Verify that DNAStatus enum exists and has correct outcomes
    assert issubclass(DNAStatus, str)
    assert hasattr(DNAStatus, "SUCCESS")
    assert hasattr(DNAStatus, "ERROR")
    assert hasattr(DNAStatus, "SKIPPED")
    assert hasattr(DNAStatus, "REFUSED")

    assert DNAStatus.SUCCESS == "success"
    assert DNAStatus.ERROR == "error"
    assert DNAStatus.SKIPPED == "skipped"
    assert DNAStatus.REFUSED == "refused"

    # Verify that DNAProcessResult exists and has standard attributes
    result = DNAProcessResult(status=DNAStatus.SUCCESS, data={"key": "val"}, error_msg="test error")
    assert result.status == DNAStatus.SUCCESS
    assert result.data == {"key": "val"}
    assert result.error_msg == "test error"

    # Verify that run_batch accepts correlation_id
    sig = inspect.signature(run_batch)
    assert "correlation_id" in sig.parameters

def test_structured_log_hygiene():
    # Capture standard output to verify log format
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        log_structured(
            correlation_id="test-corr-id",
            step="test-step",
            outcome=DNAStatus.SUCCESS,
            latency_ms=42,
            idempotency_key="test-key",
            outcome_detail="detailed outcome message"
        )
    output = f.getvalue().strip()
    assert output.startswith("JSON_LOG:")

    # Parse the logged JSON structure
    json_part = output[len("JSON_LOG:"):].strip()
    log_data = json.loads(json_part)

    # Assert existence of standard and required fields
    mandatory_fields = [
        "timestamp", "correlation_id", "actor_id", "chain_name",
        "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
    ]
    for field in mandatory_fields:
        assert field in log_data, f"Mandatory log field '{field}' is missing"

    assert log_data["correlation_id"] == "test-corr-id"
    assert log_data["step"] == "test-step"
    assert log_data["outcome"] == "success"
    assert log_data["latency_ms"] == 42
    assert log_data["idempotency_key"] == "test-key"
    assert log_data["outcome_detail"] == "detailed outcome message"
    assert log_data["actor_id"] == "orchestrator"
    assert log_data["chain_name"] == "dna_batch_parsing"

    # Check UTC ISO 8601 timestamp format: YYYY-MM-DDTHH:MM:SSZ
    assert log_data["timestamp"].endswith("Z")
    assert "T" in log_data["timestamp"]
