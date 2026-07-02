import unittest
import inspect
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator
from utils.dna_ui import log_structured

class TestMaintainability(unittest.TestCase):
    def test_dna_calculator_parse_naming(self):
        """Verify that DNACalculator.parse uses the canonical parameter name 'dna_sequence'."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_structured_log_format(self):
        """Verify that log_structured outputs JSON-prefixed logs with expected fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured("INFO", "test message", correlation_id="test-id", step="test-step")

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        log_json = json.loads(output[len("JSON_LOG: "):])
        self.assertEqual(log_json["level"], "INFO")
        self.assertEqual(log_json["message"], "test message")
        self.assertEqual(log_json["correlation_id"], "test-id")
        self.assertEqual(log_json["step"], "test-step")
        self.assertIn("timestamp", log_json)

if __name__ == "__main__":
    unittest.main()
