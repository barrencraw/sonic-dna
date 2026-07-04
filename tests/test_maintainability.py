import unittest
import json
import inspect
from utils.dna_calculator import DNACalculator
from utils.dna_ui import log_structured

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_calculator(self):
        """Ensure DNACalculator.parse uses the canonical 'dna_sequence' parameter name."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)
        self.assertNotIn('dna_string', sig.parameters)

    def test_structured_logging_format(self):
        """Verify log_structured output contains required JSON_LOG: prefix and basic fields."""
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                level="INFO",
                message="test message",
                correlation_id="test-id",
                chain_name="test-chain",
                step="test-step"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        self.assertEqual(log_data['level'], "INFO")
        self.assertEqual(log_data['message'], "test message")
        self.assertEqual(log_data['correlation_id'], "test-id")
        self.assertEqual(log_data['chain_name'], "test-chain")
        self.assertEqual(log_data['step'], "test-step")
        self.assertIn('timestamp', log_data)

if __name__ == '__main__':
    unittest.main()
