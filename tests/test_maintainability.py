import inspect
import json
import unittest
import datetime
import io
from unittest.mock import patch
from utils.dna_ui import (
    run_batch,
    DNAStatus,
    PersistenceError,
    LedgerSaveError,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify run_batch has correlation_id as a parameter with default value None."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters)
        self.assertIsNone(sig.parameters['correlation_id'].default)

    def test_dna_status_values(self):
        """Verify that DNAStatus uses lowercase string values as expected."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_typed_exceptions(self):
        """Verify LedgerSaveError subclasses PersistenceError."""
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))

    def test_structured_logging_fields(self):
        """Verify that log_structured emits JSON logs with all mandatory fields."""
        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            log_structured(
                correlation_id="test-corr-123",
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=45,
                actor_id="test-actor",
                idempotency_key="test-key",
                outcome_detail="Test detail"
            )
            output = fake_out.getvalue().strip()

        prefix = "JSON_LOG: "
        self.assertTrue(output.startswith(prefix))
        json_part = output[len(prefix):]
        log_data = json.loads(json_part)

        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data, f"Missing mandatory field: {field}")

        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 45)
        self.assertEqual(log_data["actor_id"], "test-actor")
        self.assertEqual(log_data["idempotency_key"], "test-key")
        self.assertEqual(log_data["outcome_detail"], "Test detail")

        # Verify timestamp format (ISO 8601 UTC with milliseconds and Z)
        timestamp_str = log_data["timestamp"]
        self.assertTrue(timestamp_str.endswith("Z"), "Timestamp must end with Z")
        # Try parsing it
        parsed_dt = datetime.datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        self.assertIsNotNone(parsed_dt)

if __name__ == '__main__':
    unittest.main()
