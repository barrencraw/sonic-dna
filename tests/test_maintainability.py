import unittest
import inspect
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator
from utils.dna_ui import log_structured, DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_dna_calculator_parameter_naming(self):
        """Verify DNACalculator.parse uses the canonical 'dna_sequence' name."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)
        self.assertNotIn('dna_string', sig.parameters)

    def test_structured_log_fields(self):
        """Verify log_structured output contains mandatory fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-id",
                step="test-step",
                outcome=DNAStatus.SUCCESS.value,
                actor_id="test-actor",
                idempotency_key="test-key"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        log_json = json.loads(output.replace("JSON_LOG: ", ""))
        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id",
            "chain_name", "step", "outcome",
            "latency_ms", "idempotency_key"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_json, f"Missing mandatory field: {field}")

if __name__ == '__main__':
    unittest.main()
