import unittest
import os
import json
import inspect
from utils.dna_ui import run_batch, main as alias_main, log_structured

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature_and_alias(self):
        """Verify run_batch has correlation_id and alias is main."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters)

        # Verify alias matches
        self.assertEqual(run_batch, alias_main)

    def test_log_structured_output_and_format(self):
        """Verify that log_structured emits formatted logs containing all mandatory fields."""
        import sys
        from io import StringIO

        # Redirect stdout to capture print
        captured_stdout = StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured_stdout
            log_structured(
                step="test_step",
                outcome="success",
                correlation_id="test_corr_id",
                idempotency_key="test_key",
                outcome_detail="test_detail"
            )
        finally:
            sys.stdout = old_stdout

        output = captured_stdout.getvalue().strip()

        # Verify prefix
        prefix = "JSON_LOG:"
        self.assertTrue(output.startswith(prefix), f"Log output should start with {prefix}")

        # Parse JSON
        json_part = output[len(prefix):]
        data = json.loads(json_part)

        # Verify mandatory fields:
        # timestamp, correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, outcome_detail
        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, data, f"Mandatory field '{field}' missing from log: {data}")

        # Verify timestamp is UTC ISO 8601 (ends with Z)
        timestamp = data["timestamp"]
        self.assertTrue(timestamp.endswith("Z"), f"Timestamp '{timestamp}' must end with 'Z' indicating UTC timezone.")
        self.assertEqual(len(timestamp), 20, f"Timestamp '{timestamp}' should be formatted as YYYY-MM-DDTHH:MM:SSZ")

if __name__ == '__main__':
    unittest.main()
