import unittest
import json
import inspect
import datetime
from unittest.mock import patch
import utils.dna_ui as dna_ui

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify that run_batch has correlation_id as a parameter."""
        sig = inspect.signature(dna_ui.run_batch)
        self.assertIn('correlation_id', sig.parameters)
        # Check that it has a default value of None
        self.assertIsNone(sig.parameters['correlation_id'].default)

    def test_dna_status_values(self):
        """Verify DNAStatus is a string enum with lowercase values."""
        self.assertEqual(dna_ui.DNAStatus.SUCCESS.value, "success")
        self.assertEqual(dna_ui.DNAStatus.ERROR.value, "error")
        self.assertEqual(dna_ui.DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(dna_ui.DNAStatus.REFUSED.value, "refused")

    @patch('builtins.print')
    def test_log_structured_schema(self, mock_print):
        """Verify log_structured schema, mandatory fields, prefix, and ISO 8601 timestamp."""
        dna_ui.log_structured(
            step="test_step",
            outcome="success",
            idempotency_key="test_key",
            outcome_detail="test_detail",
            correlation_id="test_corr_id"
        )

        mock_print.assert_called_once()
        print_arg = mock_print.call_args[0][0]

        # Must start with JSON_LOG:
        self.assertTrue(print_arg.startswith("JSON_LOG: "))

        # Parse the JSON part
        json_str = print_arg[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        # Check mandatory fields
        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data)

        self.assertEqual(log_data["correlation_id"], "test_corr_id")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["idempotency_key"], "test_key")
        self.assertEqual(log_data["outcome_detail"], "test_detail")

        # Validate ISO 8601 timestamp
        timestamp_str = log_data["timestamp"]
        # Should end with 'Z'
        self.assertTrue(timestamp_str.endswith('Z'))
        # Parse timestamp
        dt = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        self.assertIsNotNone(dt)

if __name__ == '__main__':
    unittest.main()
