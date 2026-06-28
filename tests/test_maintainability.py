import unittest
import os
import io
import json
import inspect
from contextlib import redirect_stdout
from utils.dna_ui import DNAStatus, log_structured
from utils.dna_calculator import DNACalculator, Rule

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_dna_sequence(self):
        """Ensure canonical name 'dna_sequence' is used in key parsing functions."""
        # Check DNACalculator.parse
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

        # Check Rule.parse
        sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_structured_logging_prefix(self):
        """Ensure structured logs have the correct prefix and are valid JSON."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured("test-id", "test-chain", "test-step", "test-outcome")

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"), "Log should start with JSON_LOG:")

        json_part = output[len("JSON_LOG:"):]
        log_data = json.loads(json_part)
        self.assertEqual(log_data["correlation_id"], "test-id")
        self.assertEqual(log_data["outcome"], "test-outcome")

    def test_dna_status_enum_values(self):
        """Ensure DNAStatus enum has the expected terminal states."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

if __name__ == '__main__':
    unittest.main()
