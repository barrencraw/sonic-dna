import unittest
import inspect
import json
import io
import sys
from unittest.mock import patch, MagicMock

from utils.dna_ui import run_batch, log_structured, DNAStatus
from utils.dna_calculator import DNACalculator, Rule

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_dna_ui(self):
        """Verify dna_ui.py uses canonical names in key functions."""
        import utils.dna_ui as dna_ui

        # Check read_input_file
        sig = inspect.signature(dna_ui.read_input_file)
        # It returns dna_sequence_list, but we can't easily check internal var names
        # without parsing the AST, but we can check if it's imported/defined.
        self.assertTrue(hasattr(dna_ui, 'DNAStatus'))

        # Check run_batch signature (it might have correlation_id now)
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters)

    def test_canonical_naming_calculator(self):
        """Verify DNACalculator.parse uses dna_sequence."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

        sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_structured_logging_format(self):
        """Verify log_structured emits the correct JSON format and prefix."""
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_structured(
                correlation_id="test-cid",
                step="test-step",
                outcome="test-outcome",
                latency_ms=100,
                idempotency_key="test-key"
            )
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        log_json = json.loads(output[9:])
        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id",
            "chain_name", "step", "outcome", "latency_ms", "idempotency_key"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_json)

        self.assertEqual(log_json["correlation_id"], "test-cid")
        self.assertEqual(log_json["step"], "test-step")
        self.assertEqual(log_json["outcome"], "test-outcome")
        self.assertEqual(log_json["latency_ms"], 100)
        self.assertEqual(log_json["idempotency_key"], "test-key")

    def test_dna_status_enum(self):
        """Verify DNAStatus has the required terminal states."""
        required = ["SUCCESS", "ERROR", "SKIPPED", "REFUSED"]
        for r in required:
            self.assertTrue(hasattr(DNAStatus, r))

if __name__ == "__main__":
    unittest.main()
