import unittest
import inspect
import io
import contextlib
import json
from utils.dna_calculator import DNACalculator
from utils.dna_ui import main as run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_dna_sequence_parameter_naming(self):
        """Verify that DNACalculator.parse uses 'dna_sequence' as parameter name."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_structured_logging_prefix(self):
        """Verify that logs emitted during processing contain the 'JSON_LOG:' prefix."""
        # We'll use a mock or capture stdout to check for the prefix
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            # Run batch with no inputs should still potentially log or we can call log_structured directly
            from utils.dna_ui import log_structured
            log_structured("INFO", "test message", correlation_id="test-id", chain_name="test-chain", step="test-step", outcome=DNAStatus.SUCCESS.value)

        output = f.getvalue()
        self.assertIn("JSON_LOG: {", output)

        # Verify it's valid JSON
        json_str = output.replace("JSON_LOG: ", "").strip()
        data = json.loads(json_str)
        self.assertEqual(data['message'], "test message")
        self.assertEqual(data['correlation_id'], "test-id")

if __name__ == '__main__':
    unittest.main()
