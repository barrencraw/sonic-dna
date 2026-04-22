import unittest
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability
import io
import sys
import json

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_structure(self):
        # Verify ParsedDNA DTO
        dna = "VOL08900750712"
        rule = "Volume"
        values = {"amplitude": 89}
        parsed = ParsedDNA(dna=dna, rule=rule, values=values)
        self.assertEqual(parsed.dna, dna)
        self.assertEqual(parsed.rule, rule)
        self.assertEqual(parsed.values, values)

    def test_outcome_enum(self):
        # Verify Outcome Enum members
        expected_members = [
            "START", "END", "SUCCESS", "ERROR", "SKIPPED",
            "PROCESSING", "NO_NEW_DNA", "PARTIAL_SUCCESS"
        ]
        for member in expected_members:
            self.assertTrue(hasattr(Outcome, member))

    def test_log_observability_schema(self):
        # Capture stdout to verify log format
        captured_output = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = captured_output

            log_observability(
                chain_name="test_chain",
                step="test_step",
                outcome=Outcome.SUCCESS,
                correlation_id="test-id",
                idempotency_key="test-key"
            )
        finally:
            sys.stdout = original_stdout

        log_line = captured_output.getvalue().strip()

        # Verify pipe-delimited format
        parts = log_line.split(" | ")
        self.assertEqual(len(parts), 6)

        # Verify JSON content
        log_data = json.loads(parts[5])
        self.assertEqual(log_data["chain_name"], "test_chain")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "SUCCESS")
        self.assertEqual(log_data["correlation_id"], "test-id")
        self.assertEqual(log_data["idempotency_key"], "test-key")
        self.assertIn("timestamp", log_data)
        self.assertIn("actor_id", log_data)

if __name__ == "__main__":
    unittest.main()
