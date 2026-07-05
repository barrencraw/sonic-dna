import unittest
import inspect
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator
from utils.dna_ui import log_structured, DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_calculator(self):
        """Verify DNACalculator.parse uses the canonical 'dna_sequence' parameter name."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse must have a 'dna_sequence' parameter")

    def test_structured_logging_format(self):
        """Verify log_structured output format and mandatory fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                "Test message",
                correlation_id="test-id",
                chain_name="test-chain",
                step="test-step",
                outcome=DNAStatus.SUCCESS.value
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "), "Log must start with 'JSON_LOG: '")

        log_json_str = output.replace("JSON_LOG: ", "")
        log_data = json.loads(log_json_str)

        mandatory_fields = ["timestamp", "message", "correlation_id", "chain_name", "step", "outcome"]
        for field in mandatory_fields:
            self.assertIn(field, log_data, f"Structured log missing mandatory field: {field}")

        self.assertEqual(log_data["correlation_id"], "test-id")
        self.assertEqual(log_data["outcome"], "success")

if __name__ == '__main__':
    unittest.main()
