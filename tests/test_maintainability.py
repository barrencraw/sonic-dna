import inspect
import json
import unittest
from utils.dna_ui import run_batch, DNAStatus, BatchResult, log_structured

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Ensure that run_batch has a correlation_id parameter in its signature."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters, "run_batch must accept a correlation_id parameter")
        # Check default value is None
        self.assertIsNone(sig.parameters['correlation_id'].default, "correlation_id parameter should default to None")

    def test_dnastatus_enum_values(self):
        """Ensure DNAStatus exists and contains lowercase canonical string values."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")
        # Verify it inherits from str
        self.assertTrue(issubclass(DNAStatus, str), "DNAStatus must be a string enum")

    def test_batchresult_structure(self):
        """Ensure BatchResult is a dataclass containing the required fields."""
        fields = BatchResult.__dataclass_fields__
        self.assertIn('status', fields)
        self.assertIn('processed_count', fields)
        self.assertIn('total_ledger_items', fields)

    def test_log_structured_keys(self):
        """Ensure log_structured emits all mandatory logging fields in expected format."""
        import io
        import contextlib

        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture):
            log_structured(
                correlation_id="test-corr-id",
                step="test-step",
                outcome="test-outcome",
                idempotency_key="test-key",
                outcome_detail="test-detail"
            )

        output = stdout_capture.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"), "Log must start with JSON_LOG: prefix")

        # Parse actual JSON
        json_str = output[len("JSON_LOG:"):]
        log_data = json.loads(json_str)

        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data, f"Structured log is missing mandatory field: {field}")

        # Check ISO 8601 formatting of timestamp ends with 'Z'
        self.assertTrue(log_data["timestamp"].endswith("Z"), "Timestamp must be in UTC ISO 8601 format and end with 'Z'")
        self.assertEqual(log_data["correlation_id"], "test-corr-id")
        self.assertEqual(log_data["step"], "test-step")
        self.assertEqual(log_data["outcome"], "test-outcome")
        self.assertEqual(log_data["idempotency_key"], "test-key")
        self.assertEqual(log_data["outcome_detail"], "test-detail")

if __name__ == '__main__':
    unittest.main()
