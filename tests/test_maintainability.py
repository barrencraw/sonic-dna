import os
import sys
import json
import unittest
from io import StringIO
from utils.dna_ui import run_batch, DNAStatus, log_structured

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum(self):
        """Verify that DNAStatus enum defines canonical outcomes and uses lowercase values."""
        self.assertTrue(hasattr(DNAStatus, 'SUCCESS'))
        self.assertTrue(hasattr(DNAStatus, 'ERROR'))
        self.assertTrue(hasattr(DNAStatus, 'SKIPPED'))
        self.assertTrue(hasattr(DNAStatus, 'REFUSED'))

        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_run_batch_signature(self):
        """Verify that run_batch has a searchable, canonical name and signature."""
        import inspect
        sig = inspect.signature(run_batch)
        params = list(sig.parameters.keys())
        self.assertIn('correlation_id', params)
        self.assertIn('actor_id', params)

    def test_structured_log_fields(self):
        """Verify that log_structured utility formats logs with the JSON_LOG: prefix and contains mandatory fields."""
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            log_structured(
                correlation_id="test_corr_123",
                actor_id="test_actor",
                chain_name="test_chain",
                step="test_step",
                outcome="success",
                latency_ms=150,
                idempotency_key="test_key",
                outcome_detail="test detail"
            )
            output = sys.stdout.getvalue().strip()
        finally:
            sys.stdout = old_stdout

        # Assert prefix
        self.assertTrue(output.startswith("JSON_LOG:"), "Log does not start with JSON_LOG:")

        # Parse JSON
        json_part = output[len("JSON_LOG:"):]
        log_data = json.loads(json_part)

        # Assert mandatory fields
        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data, f"Mandatory log field '{field}' is missing")

        # Validate content
        self.assertEqual(log_data["correlation_id"], "test_corr_123")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["chain_name"], "test_chain")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 150)
        self.assertEqual(log_data["idempotency_key"], "test_key")
        self.assertEqual(log_data["outcome_detail"], "test detail")

        # Verify timestamp format (precise ISO 8601 UTC)
        timestamp = log_data["timestamp"]
        self.assertTrue(timestamp.endswith("Z"), "Timestamp must end with 'Z' indicating UTC")
        self.assertIn("T", timestamp, "Timestamp must contain 'T' separator")

if __name__ == '__main__':
    unittest.main()
