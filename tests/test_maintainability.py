import unittest
import inspect
import json
from io import StringIO
from unittest.mock import patch
from utils.dna_calculator import DNACalculator
from utils.dna_ui import log_structured

class TestMaintainability(unittest.TestCase):
    def test_dna_calculator_parse_naming(self):
        """Verify DNACalculator.parse uses canonical parameter name 'dna_sequence'."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_log_structured_format(self):
        """Verify log_structured emits JSON_LOG: prefixed JSON with mandatory fields."""
        with patch('sys.stdout', new=StringIO()) as fake_out:
            log_structured(
                correlation_id="test-id",
                actor_id="test-actor",
                chain_name="test-chain",
                step="test-step",
                outcome="success",
                message="test-message"
            )
            output = fake_out.getvalue().strip()

            self.assertTrue(output.startswith("JSON_LOG: "))
            json_str = output.replace("JSON_LOG: ", "")
            log_data = json.loads(json_str)

            mandatory_fields = [
                "timestamp", "correlation_id", "actor_id",
                "chain_name", "step", "outcome", "message"
            ]
            for field in mandatory_fields:
                self.assertIn(field, log_data)

            self.assertEqual(log_data["correlation_id"], "test-id")
            self.assertEqual(log_data["outcome"], "success")

if __name__ == "__main__":
    unittest.main()
