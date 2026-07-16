import json
import pytest
from utils.dna_ui import run_batch, log_structured, DNAStatus

def test_run_batch_exists():
    assert callable(run_batch)

def test_dnastatus_enum():
    assert DNAStatus.SUCCESS.value == "SUCCESS"
    assert DNAStatus.ERROR.value == "ERROR"
    assert DNAStatus.SKIPPED.value == "SKIPPED"
    assert DNAStatus.REFUSED.value == "REFUSED"

def test_log_structured_output(capsys):
    correlation_id = "test-corr-id"
    step = "test-step"
    outcome = "SUCCESS"
    log_structured(correlation_id, step, outcome, latency_ms=100, idempotency_key="test-key", outcome_detail="detail")

    captured = capsys.readouterr()
    assert captured.out.startswith("JSON_LOG: ")

    log_json = json.loads(captured.out.replace("JSON_LOG: ", "").strip())

    required_fields = [
        "timestamp", "correlation_id", "actor_id", "chain_name",
        "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
    ]
    for field in required_fields:
        assert field in log_json

    assert log_json["correlation_id"] == correlation_id
    assert log_json["step"] == step
    assert log_json["outcome"] == outcome
    assert log_json["latency_ms"] == 100
    assert log_json["idempotency_key"] == "test-key"
    assert log_json["outcome_detail"] == "detail"
