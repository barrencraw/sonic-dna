import unittest
import json
import io
import contextlib
from utils.dna_ui import log_observability, Outcome

class TestSignal(unittest.TestCase):
    def test_log_observability_schema(self):
        """Assert that log_observability outputs a valid JSON with required fields."""
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            log_observability(
                chain_name="test_chain",
                step="test_step",
                outcome=Outcome.SUCCESS,
                latency_ms=123.45,
                idempotency_key="test_key"
            )

        output = f.getvalue().strip()
        log_entry = json.loads(output)

        required_keys = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key"
        }
        for key in required_keys:
            self.assertIn(key, log_entry, f"Missing required key: {key}")

        self.assertEqual(log_entry["chain_name"], "test_chain")
        self.assertEqual(log_entry["step"], "test_step")
        self.assertEqual(log_entry["outcome"], "SUCCESS")
        self.assertEqual(log_entry["latency_ms"], 123.45)
        self.assertEqual(log_entry["idempotency_key"], "test_key")

    def test_outcome_enum_values(self):
        """Ensure Outcome Enum has all required canonical names."""
        expected_values = {
            "START", "END", "SUCCESS", "ERROR", "SKIPPED", "PROCESSING", "NO_NEW_DNA"
        }
        actual_values = {o.value for o in Outcome}
        for val in expected_values:
            self.assertIn(val, actual_values, f"Outcome Enum missing value: {val}")

if __name__ == '__main__':
    unittest.main()
