import unittest
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import ParsedDNA, DNACalculator
from utils.dna_ui import Outcome, log_observability

class TestSignal(unittest.TestCase):
    def test_parsed_dna_dto(self):
        # Verify ParsedDNA structure
        dto = ParsedDNA(dna="TEST", rule="TestRule", values={"key": "val"})
        self.assertEqual(dto.dna, "TEST")
        self.assertEqual(dto.rule, "TestRule")
        self.assertEqual(dto.values, {"key": "val"})

    def test_log_observability_schema(self):
        # Capture stdout to verify log format
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                correlation_id="cid-123",
                chain_name="test_chain",
                step="test_step",
                outcome=Outcome.SUCCESS,
                idempotency_key="idemp-456"
            )
        output = f.getvalue()
        # Basic format check: [timestamp] [chain_name] [step] outcome=SUCCESS key=idemp-456
        self.assertIn("[test_chain]", output)
        self.assertIn("[test_step]", output)
        self.assertIn("outcome=SUCCESS", output)
        self.assertIn("key=idemp-456", output)

if __name__ == "__main__":
    unittest.main()
