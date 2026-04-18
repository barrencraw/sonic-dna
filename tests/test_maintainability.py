import unittest
import json
import io
import contextlib
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_outcome_enum_members(self):
        """Verify that Outcome Enum has all required members as per project memory."""
        expected_members = [
            "START", "END", "SUCCESS", "ERROR",
            "SKIPPED", "PROCESSING", "NO_NEW_DNA",
            "PARTIAL_SUCCESS"
        ]
        for member in expected_members:
            self.assertTrue(hasattr(Outcome, member), f"Outcome missing member: {member}")

    def test_log_observability_schema(self):
        """Verify that log_observability produces the correct structured log schema."""
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            log_observability(
                step="test_step",
                outcome=Outcome.SUCCESS,
                latency_ms=100,
                correlation_id="test-id",
                idempotency_key="test-key"
            )

        log_line = output.getvalue().strip()
        self.assertTrue(log_line.startswith("[OBSERVABILITY] "))

        json_part = log_line[len("[OBSERVABILITY] "):]
        log_entry = json.loads(json_part)

        required_keys = [
            "timestamp", "correlation_id", "chain_name",
            "step", "outcome", "latency_ms", "actor_id", "idempotency_key"
        ]
        for key in required_keys:
            self.assertIn(key, log_entry, f"Log entry missing key: {key}")

        self.assertEqual(log_entry["outcome"], "SUCCESS")
        self.assertEqual(log_entry["correlation_id"], "test-id")
        self.assertEqual(log_entry["idempotency_key"], "test-key")
        self.assertEqual(log_entry["latency_ms"], 100)
        self.assertEqual(log_entry["chain_name"], "dna_batch_chain")

    def test_log_observability_with_error(self):
        """Verify log_observability handles error messages correctly."""
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            log_observability(
                step="fail_step",
                outcome=Outcome.ERROR,
                error_message="something went wrong"
            )

        log_line = output.getvalue().strip()
        json_part = log_line[len("[OBSERVABILITY] "):]
        log_entry = json.loads(json_part)

        self.assertEqual(log_entry["outcome"], "ERROR")
        self.assertEqual(log_entry["error_message"], "something went wrong")

if __name__ == '__main__':
    unittest.main()
