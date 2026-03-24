import unittest
import json
import os
import io
from contextlib import redirect_stdout
from utils.dna_ui import log_observability, Outcome

class TestSignal(unittest.TestCase):
    def test_observability_fields(self):
        """
        Verify that log_observability produces JSON with the required fields.
        """
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                correlation_id="test-id",
                actor_id="test-actor",
                step="test-step",
                outcome=Outcome.SUCCESS,
                latency_ms=123.45,
                idempotency_key="test-key",
                error_msg="test-error"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("[OBSERVABILITY] "))
        json_str = output[len("[OBSERVABILITY] "):]
        log_entry = json.loads(json_str)

        required_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "error"
        ]
        for field in required_fields:
            self.assertIn(field, log_entry, f"Missing required field: {field}")

        self.assertEqual(log_entry["correlation_id"], "test-id")
        self.assertEqual(log_entry["actor_id"], "test-actor")
        self.assertEqual(log_entry["outcome"], "SUCCESS")
        self.assertEqual(log_entry["error"], "test-error")

    def test_outcome_enum_usage(self):
        """
        Verify that Outcome enum values are correctly used.
        """
        self.assertEqual(Outcome.SUCCESS.value, "SUCCESS")
        self.assertEqual(Outcome.ERROR.value, "ERROR")

if __name__ == '__main__':
    unittest.main()
