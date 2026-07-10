import unittest
import inspect
from utils.dna_calculator import DNACalculator
from utils.dna_ui import log_structured
import json
import io
from contextlib import redirect_stdout

class TestMaintainability(unittest.TestCase):
    def test_dna_calculator_parse_signature(self):
        """Regression guard for canonical naming: DNACalculator.parse must use 'dna_sequence'."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_log_structured_output_format(self):
        """Regression guard for observability hygiene: log_structured must emit JSON with specific fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-corr",
                actor_id="test-actor",
                chain_name="test-chain",
                step="test-step",
                outcome="test-outcome",
                latency_ms=100,
                idempotency_key="test-key",
                extra={"foo": "bar"}
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))
        json_str = output[len("JSON_LOG:"):]
        log_data = json.loads(json_str)

        required_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key"
        ]
        for field in required_fields:
            self.assertIn(field, log_data)

        self.assertEqual(log_data["correlation_id"], "test-corr")
        self.assertEqual(log_data["foo"], "bar")

if __name__ == '__main__':
    unittest.main()
