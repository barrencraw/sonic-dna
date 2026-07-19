import unittest
import os
import json
import inspect
from utils import dna_ui

class TestMaintainability(unittest.TestCase):
    def test_naming_conventions_and_signatures(self):
        """Ensure canonical naming and parameter signatures in utils.dna_ui."""
        # Main function must exist and accept correlation_id
        self.assertTrue(hasattr(dna_ui, 'main'), "utils.dna_ui must have a main function")
        sig = inspect.signature(dna_ui.main)
        self.assertIn('correlation_id', sig.parameters, "utils.dna_ui.main must accept correlation_id")

    def test_log_structured_fields(self):
        """Ensure that log_structured produces all required fields in the telemetry format."""
        import io
        import sys

        # Setup mock stdout to capture JSON_LOG prefix
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output

        try:
            dna_ui.log_structured(
                correlation_id="test-corr-id",
                actor_id="test-actor",
                chain_name="test-chain",
                step="test-step",
                outcome="success",
                latency_ms=42,
                idempotency_key="test-key",
                outcome_detail="test-detail"
            )
        finally:
            sys.stdout = old_stdout

        log_lines = captured_output.getvalue().strip().split('\n')
        self.assertTrue(len(log_lines) > 0, "At least one log line should be emitted")

        json_line = None
        for line in log_lines:
            if line.startswith("JSON_LOG:"):
                json_line = line[len("JSON_LOG:"):].strip()
                break

        self.assertIsNotNone(json_line, "Log must be prefixed with JSON_LOG:")

        log_data = json.loads(json_line)
        required_fields = [
            'timestamp',
            'correlation_id',
            'actor_id',
            'chain_name',
            'step',
            'outcome',
            'latency_ms',
            'idempotency_key',
            'outcome_detail'
        ]
        for field in required_fields:
            self.assertIn(field, log_data, f"Structured log must contain the '{field}' field")

        # Verify timestamp format (precise UTC ISO 8601 %Y-%m-%dT%H:%M:%SZ)
        timestamp = log_data['timestamp']
        self.assertTrue(timestamp.endswith('Z'), "Timestamp must be UTC and end with Z")
        self.assertEqual(len(timestamp), 20, "Timestamp must follow %Y-%m-%dT%H:%M:%SZ format exactly")

if __name__ == '__main__':
    unittest.main()
